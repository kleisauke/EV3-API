// Last known direction
let lastDirection = null;

// Is the robot stopped?
let isStopped = false;

// Speed of the movement motors (in percentage)
let speed = 100;

let directions = {
    37: 'left',
    38: 'forward',
    39: 'right',
    40: 'backward',
};

// Keys map
let map = {
    38: false, // Up
    40: false, // Down
    37: false, // Left
    39: false // Right
};

let output = $('#history-output'); // where output is sent

$(document).ready(function () {
    $('#up-arrow, #down-arrow, #left-arrow, #right-arrow').on('click', function () {
        let direction = $(this).data('direction');

        // Is robot moving?
        isStopped = $(this).hasClass('activated');

        // Update last known direction
        lastDirection = isStopped ? null : direction;

        // Move the robot
        moveRobot(direction, isStopped ? 0 : speed);

        // Toggle current button
        $(this).toggleClass('activated');

        // Remove previous classes
        $(this).parent().children().not($(this)).removeClass('activated');

        // Add to history
        addToHistory(isStopped ? 'Stop movement' : 'Move robot (' + direction + ')');
    });
    $('#killSwitch').click(function () {
        // Initiate kill switch
        killSwitch();

        let button = $(this);

        // Toggle active class
        setTimeout(function () {
            button.removeClass('active');
        }, 100);
        button.addClass('active');

        // Add to history
        addToHistory('Kill switch initiated');
    });
    $('#submitConfig').click(function () {
        let leftSide = $('#leftSide').val();
        let leftType = $('#leftType').val();
        let rightSide = $('#rightSide').val();
        let rightType = $('#rightType').val();

        let config = {
            'left': {
                'address': leftSide,
                'type': leftType
            },
            'right': {
                'address': rightSide,
                'type': rightType
            }
        };

        updateMovementConfig(config);
    });
    $('#speed').on('input', function () {
        speed = $(this).val();
    });
});

$(document).keydown(function (event) {
    let keycode = (event.keyCode ? event.keyCode : event.which);
    // Spacebar is being pressed
    if (keycode === 32) {
        if (!isStopped) {
            stopMovement();

            // Robot is stopped
            isStopped = true;

            // Unset last known direction
            lastDirection = null;

            addToHistory('Stop movement');

            $('.keys').children().removeClass('activated');
        }
    } else if (keycode in map) {
        // Indicator
        switch (keycode) {
            case 38:
                $('#up-arrow').addClass('activated');
                break;
            case 40:
                $('#down-arrow').addClass('activated');
                break;
            case 37:
                $('#left-arrow').addClass('activated');
                break;
            case 39:
                $('#right-arrow').addClass('activated');
                break;
        }

        // If it's a first press
        // And if it's not yet turning towards that direction
        let direction = directions[keycode];
        if (map[keycode] === false && direction !== lastDirection) {
            // Move the robot
            moveRobot(direction, speed);

            // Robot is moving
            isStopped = false;

            // Update last known direction
            lastDirection = direction;

            addToHistory('Move robot (' + direction + ')');
        }

        map[keycode] = true;
    }
}).keyup(function (event) {
    let keycode = (event.keyCode ? event.keyCode : event.which);
    if (keycode in map) {
        // Indicator
        switch (keycode) {
            case 38:
                $('#up-arrow').removeClass('activated');
                break;
            case 40:
                $('#down-arrow').removeClass('activated');
                break;
            case 37:
                $('#left-arrow').removeClass('activated');
                break;
            case 39:
                $('#right-arrow').removeClass('activated');
                break;
        }

        // Set the specific key to false
        map[keycode] = false;

        // Check if all keys are false
        let allFalse = Object.keys(map).every(function (k) {
            return !this[k];
        }, map);

        // If so we need to stop the movement (if it's not stopped already)
        if (allFalse) {
            if (!isStopped) {
                stopMovement();

                // Robot is stopped
                isStopped = true;

                // Unset last known direction
                lastDirection = null;

                $('.keys').children().removeClass('activated');

                addToHistory('Stop movement');
            }
        } else {
            // Two or more keys are pressed.
            Object.keys(map).every(function (k) {
                // Check for every value if it's true
                // and if it's not yet turning towards that direction
                let direction = directions[k];
                if (this[k] && direction !== lastDirection) {
                    // Move the robot
                    moveRobot(direction, speed);

                    // Robot is moving
                    isStopped = false;

                    // Update last known direction
                    lastDirection = direction;

                    // Break the loop
                    return false;
                }
                return true;
            }, map);
        }
    }
});

/**
 * Add text to history
 *
 * @param {String} text Text to display
 */
function addToHistory(text) {
    let time = moment().format('HH:mm:ss');

    // Create a new line for log
    let line = $('<li class="list-group-item" />');

    // Filter out html from messages
    let message = $('<span class="text" />').text(time + ' ' + text).html();

    // Build the html elements
    line.append(message);
    output.append(line);

    // scroll the history output to the bottom
    output.scrollTop(output[0].scrollHeight);
}

/**
 * Motor API.
 */

/**
 * Starts or stops one or several motor(s)
 *
 * @param {String} addresses Address(es) of the motor(s) to start/stop
 * @param {Number} speed Set the duty cycle of the motor (from -100 to 100, 0 to stop)
 */
function startMotor(addresses, speed) {
    let url = `/api/motor/${addresses}/${speed}`;

    // Send the data using post
    $.post(url).done(function (data) {
        console.log(data);
    }).fail(function (xhr, textStatus, errorThrown) {
        console.log(xhr.responseText);
    });
}

/**
 * Get the current speed of a motor
 *
 * @param {String} address Address of the motor to get the speed from
 */
function getMotorStatus(address) {
    let url = `/api/motor/${address}`;

    // Get the data using get
    $.get(url).done(function (data) {
        console.log(data.speed);
    }).fail(function (xhr, textStatus, errorThrown) {
        console.log(xhr.responseText);
    });
}

/**
 * Shut off all motors
 */
function killSwitch() {
    let url = '/api/motor/killswitch';

    // Send the data using post
    $.post(url).done(function (data) {
        console.log(data);
    }).fail(function (xhr, textStatus, errorThrown) {
        console.log(xhr.responseText);
    });
}

/**
 * Movement API.
 */

/**
 * Move robot towards a specific direction
 *
 * @param {String} direction Direction
 * @param {Number} speed Set the speed of the motor (in percentage)
 */
function moveRobot(direction, speed) {
    let url = `/api/movement/${direction}/${speed}`;

    // Send the data using post
    $.post(url).done(function (data) {
        console.log(data);
    }).fail(function (xhr, textStatus, errorThrown) {
        console.log(xhr.responseText);
    });
}


/**
 * Set the motor address and type of a side
 *
 * @param {Object} config Config
 */
function updateMovementConfig(config) {
    let url = '/api/movement/config';

    $.ajax({
        type: 'POST',
        url: url,
        data: JSON.stringify(config),
        success: function (data) {
            console.log(data);
        },
        error: function (xhr, textStatus, errorThrown) {
            console.log(xhr.responseText);
        },
        contentType: 'application/json',
        dataType: 'json'
    });
}

/**
 * Stops any movement
 */
function stopMovement() {
    let url = '/api/movement/forward/0';

    // Send the data using post
    $.post(url).done(function (data) {
        console.log(data);
    }).fail(function (xhr, textStatus, errorThrown) {
        console.log(xhr.responseText);
    });
}

/**
 * Sound API.
 */

/**
 * Add a .wav file
 *
 * @param {File} upload Send a .wav file
 */
function addSound(upload) {
    let url = '/api/sound';

    // Send the data using post
    $.post(url, {upload: upload}).done(function (data) {
        console.log(data);
    }).fail(function (xhr, textStatus, errorThrown) {
        console.log(xhr.responseText);
    });
}

/**
 * Plays a specific sound
 *
 * @param {Number} soundId ID of the sound to play
 */
function playSound(soundId) {
    let url = `/api/sound/${soundId}`;

    // Send the data using post
    $.post(url).done(function (data) {
        console.log(data);
    }).fail(function (xhr, textStatus, errorThrown) {
        console.log(xhr.responseText);
    });
}

/**
 * Execute text-to-speech
 *
 * @param {String} text Text to speech
 */
function speak(text) {
    let url = `/api/sound/tts/${text}`;

    // Send the data using post
    $.post(url).done(function (data) {
        console.log(data);
    }).fail(function (xhr, textStatus, errorThrown) {
        console.log(xhr.responseText);
    });
}

/**
 * Add a .bmp file
 *
 * @param {File} upload Send a .bmp file
 */
function addBitmap(upload) {
    let url = '/api/image';

    // Send the data using post
    $.post(url, {upload: upload}).done(function (data) {
        console.log(data);
    }).fail(function (xhr, textStatus, errorThrown) {
        console.log(xhr.responseText);
    });
}

/**
 * Display a specific image
 *
 * @param {Number} imageId ID of the image to display
 * @param {Number} timeInSec Time in seconds (0 for infinite) to display
 */
function displayImage(imageId, timeInSec) {
    let url = `/api/image/${imageId}/${timeInSec}`;

    // Send the data using post
    $.post(url).done(function (data) {
        console.log(data);
    }).fail(function (xhr, textStatus, errorThrown) {
        console.log(xhr.responseText);
    });
}
