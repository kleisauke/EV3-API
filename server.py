#!/usr/bin/env python

import os
import uuid
import time
import logging

import hug
import json
import threading
import ev3dev.ev3 as ev3

from PIL import Image
from hug.api import INTRO
from falcon import HTTP_400, HTTP_200
from wsgiref.simple_server import make_server
from marshmallow import fields
from marshmallow.validate import Range, OneOf, ContainsOnly, Length

from client import Client
from schemas import SensorSchema, RobotSchema, ActionSchema, MovementSideSchema, MotorSchema

"""
Global variables
"""
# Create logger
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Define port number to serve on
port_number = 80

# Is kill switch initiated?
kill_switch = False

"""
Threading
"""


class MovementControl(threading.Thread):
    """Simple thread dealing with driving motors"""

    def __init__(self, movement_dict):
        self.motors = movement_dict
        self.running = True
        self.speed_left = 0
        self.speed_right = 0
        self.e = threading.Event()
        threading.Thread.__init__(self)

    def run(self):
        while self.running:
            # Block until the internal flag is true.
            self.e.wait()
            for side, motor in self.motors.items():
                if not motor.connected:
                    continue

                if side == 'left':
                    motor.run_direct(duty_cycle_sp=self.speed_left)
                elif side == 'right':
                    motor.run_direct(duty_cycle_sp=self.speed_right)
            # Reset the internal flag to false.
            self.e.clear()

    def stop(self):
        self.running = False
        for side, motor in self.motors.items():
            motor.stop()
        self.e.set()

    def set_speed(self, speed_left, speed_right):
        self.speed_left = speed_left
        self.speed_right = speed_right
        self.e.set()

    def update_motors(self, movement_dict):
        """Update the motors"""
        self.motors = movement_dict


class SensorControl(threading.Thread):
    """Simple thread dealing with sensor control"""

    def __init__(self, sensors_dict, actions):
        self.sensors = sensors_dict
        self.actions = actions
        self.current_actions = {}
        self.running = True
        threading.Thread.__init__(self)

    def run(self):
        while self.running:
            for action in self.actions:
                address = action['address']

                if address not in self.sensors or not self.sensors[address].connected:
                    continue

                sensor = self.sensors[address]

                value_key = action['action']
                if value_key == 'is_pressed' and isinstance(sensor, ev3.TouchSensor):
                    value = sensor.is_pressed
                elif value_key == 'distance_centimeters' and isinstance(sensor, ev3.UltrasonicSensor):
                    value = sensor.distance_centimeters
                elif value_key == 'proximity' and isinstance(sensor, ev3.InfraredSensor):
                    value = sensor.proximity
                elif value_key == 'rate' and isinstance(sensor, ev3.GyroSensor):
                    value = sensor.rate
                elif value_key == 'angle' and isinstance(sensor, ev3.GyroSensor):
                    value = sensor.angle
                elif value_key == 'color' and isinstance(sensor, ev3.ColorSensor):
                    value = sensor.color
                else:
                    continue

                exec_actions = self.current_actions[address] if address in self.current_actions else []
                comparison = action['condition']['comparison']
                compare_with = action['condition']['compare_with']
                when_true = action['when_true']
                when_false = action['when_false']

                if comparison == '==':
                    if value == compare_with:
                        exec_actions = when_true
                    else:
                        exec_actions = when_false
                elif comparison == '!=':
                    if value != compare_with:
                        exec_actions = when_true
                    else:
                        exec_actions = when_false
                elif comparison == '>':
                    if value > compare_with:
                        exec_actions = when_true
                    else:
                        exec_actions = when_false
                elif comparison == '<':
                    if value < compare_with:
                        exec_actions = when_true
                    else:
                        exec_actions = when_false
                elif comparison == '>=':
                    if value >= compare_with:
                        exec_actions = when_true
                    else:
                        exec_actions = when_false
                elif comparison == '<=':
                    if value <= compare_with:
                        exec_actions = when_true
                    else:
                        exec_actions = when_false
                elif comparison == 'between':
                    compare_with2 = action['condition']['compare_with2']
                    # Interval comparison (same as `value >= compare_with and value <= compare_with2`):
                    if compare_with <= value <= compare_with2:
                        exec_actions = when_true
                    else:
                        exec_actions = when_false

                # Do the action once
                if address in self.current_actions and self.current_actions[address] == exec_actions:
                    continue

                execute_action = ExecuteAction(exec_actions)
                execute_action.start()

                self.current_actions[address] = exec_actions

    def update_sensors(self, sensors_dict):
        """Update the sensors"""
        self.sensors = sensors_dict

    def update_actions(self, actions):
        """Update actions"""
        self.actions = actions

    def stop(self):
        self.running = False


class ExecuteAction(threading.Thread):
    """Simple thread dealing with the execution of actions"""

    def __init__(self, exec_actions):
        self.exec_actions = exec_actions
        threading.Thread.__init__(self)

    def run(self):
        for action in self.exec_actions:
            global kill_switch  # Needed to modify global copy of kill_switch
            if kill_switch:
                kill_switch = False
                break

            if action['method'] == 'POST':
                body = ''
                if 'body' in action:
                    body = action['body']
                result = client.post(action['url'], body)
            elif action['method'] == 'GET':
                result = client.get(action['url'])
            # if action['method'] == 'DELETE':
            else:
                result = client.delete(action['url'])

            # Should we wait before performing another action?
            if 'wait' in action:
                time.sleep(action['wait'])

            log.info('Action successfully executed.\nAction: %s\nResult: %s' % (json.dumps(action), result.data))


class ScreenControl(threading.Thread):
    """Simple thread dealing with the screen of the brick"""

    def __init__(self):
        self.image = None
        self.timeout = -1
        self.screen = None
        self.running = True
        self.e = threading.Event()
        threading.Thread.__init__(self)

    def run(self):
        while self.running:
            # Block until the internal flag is true.
            self.e.wait()

            # Run the loop for a amount of time
            if self.timeout != 0 and time.time() > self.timeout:
                # Reset the internal flag to false.
                self.e.clear()

                # Clear the screen
                self.screen.clear()
                self.screen.update()
            else:
                self.screen.image.paste(self.image, (0, 0))
                self.screen.update()

    def display(self, pil_image, timeout):
        """Display a bitmap on the brick's display for an amount of time"""
        self.screen = ev3.Screen()
        self.image = pil_image
        self.timeout = timeout
        self.e.set()

    def stop(self):
        self.running = False


"""
Helpers
"""


def read_json(filename):
    """Read data from a file"""
    with open(filename, encoding='utf-8', mode='r') as f:
        data = json.load(f)
    return data


def save_json(filename, data):
    """Write data to a file"""
    with open(filename, encoding='utf-8', mode='w') as f:
        json.dump(data, f, indent=4, sort_keys=False, separators=(',', ': '))
    return data


def parse_sensor_config(sensor_config):
    """Parse the sensor config and assign them to a specific sensor class"""
    data = {}
    for address, sensor_type in sensor_config.items():
        # Append to dict if it's a valid sensor type
        if sensor_type == 'color':
            color_sensor = ev3.ColorSensor(address)
            # Only add to dict if color sensor is connected
            if color_sensor.connected:
                data[address] = color_sensor
            else:
                log.error('%s is not connected' % color_sensor)
        elif sensor_type == 'gyro':
            gyro_sensor = ev3.GyroSensor(address)
            # Only add to dict if gyro sensor is connected
            if gyro_sensor.connected:
                data[address] = gyro_sensor
            else:
                log.error('%s is not connected' % gyro_sensor)
        elif sensor_type == 'infrared':
            infrared_sensor = ev3.InfraredSensor(address)
            # Only add to dict if infrared sensor is connected
            if infrared_sensor.connected:
                data[address] = infrared_sensor
            else:
                log.error('%s is not connected' % infrared_sensor)
        elif sensor_type == 'touch':
            touch_sensor = ev3.TouchSensor(address)
            # Only add to dict if touch sensor is connected
            if touch_sensor.connected:
                data[address] = touch_sensor
            else:
                log.error('%s is not connected' % touch_sensor)
        elif sensor_type == 'ultrasonic':
            ultrasonic_sensor = ev3.UltrasonicSensor(address)
            # Only add to dict if ultrasonic sensor is connected
            if ultrasonic_sensor.connected:
                data[address] = ultrasonic_sensor
            else:
                log.error('%s is not connected' % ultrasonic_sensor)
    return data


def parse_motor_config(motor_config):
    """Parse the motor config and assign them to a specific motor class"""
    data = {}
    for address, motor_type in motor_config.items():
        # Append to dict if it's a valid motor type
        if motor_type == 'large':
            large_motor = ev3.LargeMotor(address)
            # Only add to dict if large motor is connected
            if large_motor.connected:
                data[address] = large_motor
            else:
                log.error('%s is not connected' % large_motor)
        elif motor_type == 'medium':
            medium_motor = ev3.MediumMotor(address)
            # Only add to dict if gyro sensor is connected
            if medium_motor.connected:
                data[address] = medium_motor
            else:
                log.error('%s is not connected' % medium_motor)
    return data


def parse_movement_config(movement_config):
    data = {}
    for side, motorDict in movement_config.items():
        # Only add to dict if value is not empty
        if not motorDict['address']:
            continue

        # Add to dict
        if motorDict['type'] == 'large':
            large_motor = ev3.LargeMotor(motorDict['address'])
            # Only add to dict if large motor is connected
            if large_motor.connected:
                data[side] = large_motor
            else:
                log.error('%s is not connected' % large_motor)
        elif motorDict['type'] == 'medium':
            medium_motor = ev3.MediumMotor(motorDict['address'])
            # Only add to dict if motor medium is connected
            if medium_motor.connected:
                data[side] = medium_motor
            else:
                log.error('%s is not connected' % medium_motor)
    return data


"""
Main config
"""

config = read_json('config.json')
motors = parse_motor_config(config['motors'])
sensors = parse_sensor_config(config['sensors'])
movement = parse_movement_config(config['movement'])

"""
Hug routes
"""


@hug.static('/')
def webapp():
    return os.path.join(os.getcwd(), 'webapp'),


@hug.static('/api')
def swagger_api():
    return os.path.join(os.getcwd(), 'docs'),


@hug.not_found()
def not_found():
    return {'message': '404 Not Found', 'code': 404}


@hug.post('/api/config')
def set_config(body: fields.Nested(RobotSchema)):
    """Set config"""
    global config  # Needed to modify global copy of config
    config = body

    # Save config
    save_json('config.json', config)

    global motors  # Needed to modify global copy of motors
    motors = parse_motor_config(config['motors'])

    global sensors  # Needed to modify global copy of sensors
    sensors = parse_sensor_config(config['sensors'])

    global movement  # Needed to modify global copy of movement
    movement = parse_movement_config(config['movement'])

    movement_control.update_motors(movement)
    sensor_control.update_sensors(sensors)
    sensor_control.update_actions(config['actions'])

    return {'message': 'Config successfully set', 'code': 200}


@hug.get('/api/config')
def get_config():
    """Set config"""
    return config


@hug.post('/api/motor/config/')
def set_motor_config(body: fields.Nested(MotorSchema)):
    """Create a list of motors to control"""
    config['motors'] = body

    # Save config
    save_json('config.json', config)

    global motors  # Needed to modify global copy of motors
    motors = parse_motor_config(config['motors'])

    movement_control.update_motors(motors)

    return {'message': 'Motors successfully defined', 'code': 200}


@hug.get('/api/motor/config/')
def get_motor_config():
    """Get a list of motors"""
    return config['motors']


@hug.post('/api/movement/config/')
def set_movement_config(body: fields.Nested(MovementSideSchema)):
    """Defines the motor address and type of a side"""
    config['movement'] = body

    # Save config
    save_json('config.json', config)

    global movement  # Needed to modify global copy of movement
    movement = parse_movement_config(config['movement'])

    movement_control.update_motors(movement)

    return {'message': 'Movement motors successfully defined', 'code': 200}


@hug.get('/api/movement/config/')
def get_movement_config():
    """Get movement config"""
    return config['movement']


@hug.post('/api/sensor/config')
def set_sensor_config(body: fields.Nested(SensorSchema)):
    """Create a list of sensors to get values from"""
    config['sensors'] = body

    # Save config
    save_json('config.json', config)

    global sensors  # Needed to modify global copy of sensors
    sensors = parse_sensor_config(config['sensors'])

    sensor_control.update_sensors(sensors)

    return {'message': 'Sensors successfully defined', 'code': 200}


@hug.get('/api/sensor/config')
def get_sensor_config():
    """Get a list of sensors"""
    return config['sensors']


@hug.post('/api/action/config')
def set_actions(body: fields.Nested(ActionSchema, many=True)):
    """Create a list of actions"""
    config['actions'] = body

    # Save config
    save_json('config.json', config)

    sensor_control.update_actions(config['actions'])

    return {'action_ids': range(len(config['actions']))}


@hug.get('/api/action/config')
def get_actions():
    """Get actions config"""
    return config['actions']


@hug.post('/api/motor/killswitch')
def set_kill_switch(response):
    """Shut off all motors"""
    # Shut off movement motors
    movement_control.set_speed(0, 0)

    # Shut off other motors
    for address in motors:
        motors[address].stop()

    global kill_switch  # Needed to modify global copy of kill_switch
    kill_switch = True

    response.status = HTTP_200
    return {'message': 'All motors successfully stopped', 'code': 200}


@hug.post('/api/motor/{address}/{duty_cycle}')
def start_motor(address: fields.Str(validate=[Length(min=1), ContainsOnly(['A', 'B', 'C', 'D'])]),
                duty_cycle: fields.Int(validate=Range(min=-100, max=100)),
                response):
    """Starts or stops one or several motor(s)"""
    result = {'messages': [], 'code': 200}
    for single_address in address:
        single_address = 'out' + single_address
        if single_address not in motors:
            error = 'Motor (address %s) is not defined yet' % single_address

            # Append the error to the existing array
            result['messages'].append(error)

            log.error(error)

            response.status = HTTP_400
            result['code'] = 400
            continue

        motor = motors[single_address]

        if not motor.connected:
            error = '%s is not connected' % motor

            # Append the error to the existing array
            result['messages'].append(error)

            response.status = HTTP_400
            result['code'] = 400
            continue

        motor.run_direct(duty_cycle_sp=duty_cycle)

        message = 'Motor (address %s) successfully ' % single_address
        message += 'stopped' if duty_cycle == 0 else 'started'
        result['messages'].append(message)

    return result


@hug.get('/api/motor/{address}')
def get_motor_status(address: fields.Str(validate=OneOf(['outA', 'outB', 'outC', 'outD'])),
                     response):
    """
    Get the current state and duty_cycle of a motor. Possible states are
    `running`, `ramping`, `holding`, `overloaded` and `stalled`.
    """
    if address in motors:
        motor = motors[address]
    else:
        # Motor not defined, just get the value from it
        motor = ev3.Motor(address)

    if not motor.connected:
        log.error('%s is not connected' % motor)
        response.status = HTTP_400
        return {'message': 'Motor not connected', 'code': 400}

    return {'state': motor.state, 'duty_cycle': motor.duty_cycle}


@hug.delete('/api/motor/{address}')
def delete_motor(address: fields.Str(validate=OneOf(['outA', 'outB', 'outC', 'outD'])),
                 response):
    """Delete the motor by a specific address"""
    if address in motors:
        motor = motors[address]

        # Stop the motor before deleting
        motor.stop()

        # Delete from motors dict
        del motors[address]

        # Delete from config
        del config['motors'][address]

        # Save config
        save_json('config.json', config)

        return {'message': 'Specific motor successfully deleted', 'code': 200}
    else:
        response.status = HTTP_400
        return {'message': 'Motor address unknown', 'code': 400}


@hug.post('/api/movement/{direction}/{speed_percentage}')
def move_to_direction(direction: fields.Str(validate=OneOf(['forward', 'backward', 'left', 'right'])),
                      speed_percentage: fields.Int(validate=Range(min=0, max=100))):
    """Move robot towards a specific direction"""
    left_speed = speed_percentage
    right_speed = speed_percentage
    if direction == 'forward':
        left_speed *= -1
        right_speed *= -1
    elif direction == 'left':
        right_speed *= -1
    elif direction == 'right':
        left_speed *= -1
    movement_control.set_speed(left_speed, right_speed)
    return {'movement': 'none' if speed_percentage == 0 else direction}


@hug.get('/api/sensor/{address}')
def get_sensor_value(address: fields.Str(validate=OneOf(['in1', 'in2', 'in3', 'in4'])),
                     response):
    """Get the sensor value from an address"""
    if address in sensors:
        sensor = sensors[address]
        sensor_type = config['sensors'][address]
    else:
        # Sensor not defined, just get the value from it
        sensor = ev3.Sensor(address)
        sensor_type = 'unknown'

    if not sensor.connected:
        log.error('%s is not connected' % sensor)
        response.status = HTTP_400
        return {'message': 'Sensor not connected', 'code': 400}

    return {'value': sensor.value(), 'type': sensor_type}


@hug.delete('/api/sensor/{address}')
def delete_sensor(address: fields.Str(validate=OneOf(['in1', 'in2', 'in3', 'in4'])),
                  response):
    """Delete the sensor by a specific address"""
    if address in sensors:
        # Delete from sensors dict
        del sensors[address]

        # Delete from config
        del config['sensors'][address]

        # Save config
        save_json('config.json', config)

        return {'message': 'Specific sensor successfully deleted', 'code': 200}
    else:
        response.status = HTTP_400
        return {'message': 'Sensor address unknown', 'code': 400}


@hug.post('/api/action/{action_id}')
def insert_action(action_id: hug.types.number,
                  body: fields.Nested(ActionSchema),
                  response):
    """Insert an action before the given action id"""
    config['actions'].insert(action_id, body)

    # Save config
    save_json('config.json', config)

    sensor_control.update_actions(config['actions'])

    return {'message': 'Action successfully inserted', 'code': 200}


@hug.get('/api/action/{action_id}')
def get_action(action_id: hug.types.number,
               response):
    """Get action for a specific id"""
    try:
        return config['actions'][action_id]
    except IndexError:
        log.error('Action ID out of range')
        response.status = HTTP_400
        return {'message': 'Action ID out of range', 'code': 400}


@hug.delete('/api/action/{action_id}')
def remove_action(action_id: hug.types.number,
                  response):
    """Delete action for a specific id"""
    try:
        del config['actions'][action_id]

        # Save config
        save_json('config.json', config)

        sensor_control.update_actions(config['actions'])

        return {'message': 'Action successfully deleted', 'code': 200}
    except IndexError:
        log.error('Action ID out of range')
        response.status = HTTP_400
        return {'message': 'Action ID out of range', 'code': 400}


@hug.post('/api/sound/tts/{text}')
def speak_text(text):
    """Text to speech"""
    ev3.Sound.speak(text)
    return {'message': 'Text-to-speech successfully executed', 'code': 200}


@hug.post('/api/sound/{sound_id}')
def play_sound(sound_id: hug.types.number, response):
    """Play a wav file with the specified id"""
    try:
        sound = config['sounds'][sound_id]
        ev3.Sound.play(sound)
        return {'message': 'Sound successfully played', 'code': 200}
    except IndexError:
        log.error('Sound ID out of range')
        response.status = HTTP_400
        return {'message': 'Sound ID out of range', 'code': 400}


@hug.post('/api/sound')
def add_sound(body, response):
    """Add a wav file"""
    # <body> is a simple dictionary of {filename: b'content'}
    file = list(body.values()).pop()
    if file is not None:
        save_path = 'sounds'
        if not os.path.exists(save_path):
            os.makedirs(save_path)

        # filename = '{0}{1}'.format(list(body.keys()).pop(), '.wav')
        unique_filename = '{0}{1}'.format(uuid.uuid4(), '.wav')
        file_path = os.path.join(save_path, unique_filename)

        with open(file_path, 'wb') as f:
            f.write(file)

        config['sounds'].append(file_path)

        # Save config
        save_json('config.json', config)

        return {'message': 'Sound successfully saved', 'id': len(config['sounds']) - 1, 'code': 200}
    else:
        log.error('No file selected')
        response.status = HTTP_400
        return {'message': 'No file selected', 'code': 400}


@hug.delete('/api/sound/{sound_id}')
def delete_sound(sound_id: hug.types.number, response):
    """Delete a specific sound by id"""
    try:
        del config['sounds'][sound_id]

        # Save config
        save_json('config.json', config)

        return {'message': 'Sound successfully deleted', 'code': 200}
    except IndexError:
        log.error('Sound ID out of range')
        response.status = HTTP_400
        return {'message': 'Sound ID out of range', 'code': 400}


@hug.post('/api/image/{image_id}/{time_in_sec}')
def display_image(image_id: hug.types.number, time_in_sec: hug.types.number, response):
    """Display a bitmap on the brick's display for an amount of time"""
    try:
        img = Image.open(config['images'][image_id])
        timeout = 0 if time_in_sec == 0 else time.time() + time_in_sec

        screen_control.display(img, timeout)

        return {'message': 'Image successfully displayed', 'code': 200}
    except IndexError:
        log.error('Image ID out of range')
        response.status = HTTP_400
        return {'message': 'Image ID out of range', 'code': 400}


@hug.post('/api/image')
def add_image(body, response):
    """Add an image"""
    # <body> is a simple dictionary of {filename: b'content'}
    file = list(body.values()).pop()
    if file is not None:
        save_path = 'images'
        if not os.path.exists(save_path):
            os.makedirs(save_path)

        # filename = '{0}{1}'.format(list(body.keys()).pop(), '.bmp')
        unique_filename = '{0}{1}'.format(uuid.uuid4(), '.bmp')
        file_path = os.path.join(save_path, unique_filename)

        with open(file_path, 'wb') as f:
            f.write(file)

        config['images'].append(file_path)

        # Save config
        save_json('config.json', config)

        return {'message': 'Image successfully saved', 'id': len(config['images']) - 1, 'code': 200}
    else:
        log.error('No file selected')
        response.status = HTTP_400
        return {'message': 'No file selected', 'code': 400}


@hug.delete('/api/image/{image_id}')
def delete_image(image_id: hug.types.number, response):
    """Delete a specific image by id"""
    try:
        del config['images'][image_id]

        # Save config
        save_json('config.json', config)

        return {'message': 'Image successfully deleted', 'code': 200}
    except IndexError:
        log.error('Sound ID out of range')
        response.status = HTTP_400
        return {'message': 'Sound ID out of range', 'code': 400}


"""
Server/client
"""

# Define API server
app = hug.API(__name__).http.server()

# Define Client
client = Client(app)

if __name__ == '__main__':
    print(INTRO)

    # Start threads
    movement_control = MovementControl(movement)
    movement_control.setDaemon(True)
    movement_control.start()

    sensor_control = SensorControl(sensors, config['actions'])
    sensor_control.setDaemon(True)
    sensor_control.start()

    screen_control = ScreenControl()
    screen_control.setDaemon(True)
    screen_control.start()

    # Create a server listening on a specific port number
    httpd = make_server('', port_number, app)
    print("Serving on port {0}...".format(port_number))
    httpd.serve_forever()
