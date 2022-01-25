const axios = require('axios');

exports.lambdaHandler = async (event, context) => {
    console.log('Running On: ',process.arch );
    console.log('Event: ',event );
    const body = JSON.parse(event.body);
    let res = await axios.get('http://numbersapi.com/'+ body.number + '/' + body.type);
    console.log('res: ',res );
    const responsebody = 'Running on:' + process.arch + ' - ' + res.data

    const response = {
        "isBase64Encoded": false,
        "headers": {
            "Content-Type": "application/json",
        },
        "statusCode": 200,
        "body": responsebody
    };
    return response;
};