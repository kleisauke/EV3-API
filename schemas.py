#!/usr/bin/env python
from marshmallow import Schema, fields
from marshmallow.validate import OneOf


class MovementSchema(Schema):
    address = fields.Str(validate=OneOf(['outA', 'outB', 'outC', 'outD']), required=True)
    type = fields.Str(validate=OneOf(['medium', 'large']), required=True)


class MovementSideSchema(Schema):
    left = fields.Nested(MovementSchema, required=False)
    right = fields.Nested(MovementSchema, required=False)


class MotorSchema(Schema):
    outA = fields.Str(validate=OneOf(['medium', 'large']), required=False)
    outB = fields.Str(validate=OneOf(['medium', 'large']), required=False)
    outC = fields.Str(validate=OneOf(['medium', 'large']), required=False)
    outD = fields.Str(validate=OneOf(['medium', 'large']), required=False)


class SensorSchema(Schema):
    in1 = fields.Str(validate=OneOf(['touch', 'color', 'gyro', 'infrared', 'ultrasonic']), required=False)
    in2 = fields.Str(validate=OneOf(['touch', 'color', 'gyro', 'infrared', 'ultrasonic']), required=False)
    in3 = fields.Str(validate=OneOf(['touch', 'color', 'gyro', 'infrared', 'ultrasonic']), required=False)
    in4 = fields.Str(validate=OneOf(['touch', 'color', 'gyro', 'infrared', 'ultrasonic']), required=False)


class ConditionSchema(Schema):
    comparison = fields.Str(validate=OneOf(['==', '!=', '>', '<', '>=', '<=', 'between']), required=True)
    compare_with = fields.Int(required=True)
    compare_with2 = fields.Int(required=False)


class ApiCall(Schema):
    method = fields.Str(validate=OneOf(['POST', 'GET', 'DELETE']), required=True)
    body = fields.Str(required=False)
    url = fields.Str(required=True)
    wait = fields.Int(required=False)


class ActionSchema(Schema):
    address = fields.Str(validate=OneOf(['in1', 'in2', 'in3', 'in4']), required=True)
    action = fields.Str(validate=OneOf([
        'is_pressed',
        'distance_centimeters',
        'proximity',
        'rate',
        'angle',
        'color'
    ]), required=True)
    condition = fields.Nested(ConditionSchema, required=True)
    when_true = fields.Nested(ApiCall, many=True, required=True)
    when_false = fields.Nested(ApiCall, many=True, required=True)


class RobotSchema(Schema):
    movement = fields.Nested(MovementSideSchema, required=True)
    motors = fields.Nested(MotorSchema, required=True)
    sensors = fields.Nested(SensorSchema, required=True)
    actions = fields.Nested(ActionSchema, many=True, required=True)
    images = fields.List(fields.Str(), required=True)
    sounds = fields.List(fields.Str(), required=True)
