from flask import Flask, jsonify, make_response, request
from flask_jwt_extended import create_access_token, jwt_required, JWTManager, get_jwt, get_jwt_identity
from flask_cors import CORS
from flask_pymongo import PyMongo
from datetime import timedelta
import requests
import json
import uuid
import time
import os

PORT = os.environ.get('PORT')
AICVD_URL = os.environ.get('AICVD_URL')
AICVD_OAUTH_TOKEN = os.environ.get('AICVD_OAUTH_TOKEN')
APOLLO247_URL = os.environ.get('APOLLO247_URL')
APOLLO247_TOKEN = os.environ.get('APOLLO247_TOKEN')
REPORT_URL = os.environ.get('REPORT_URL')
MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017/bridge_data")

app = Flask(__name__)

app.config["MONGO_URI"] = MONGODB_URL 
mongo = PyMongo(app)
db = mongo.db


SECRET_KEY = os.environ.get('SECRET_KEY')
app.config["JWT_SECRET_KEY"] = SECRET_KEY
jwt = JWTManager(app)

def insert_data(data, collection_name):
    try: 
        inserted_id = db[collection_name].insert_one(data)
        return True, inserted_id.inserted_id
    except Exception as e:
        print('---------- Error in insert data method ---------')
        print(e)
        print('-------------------')
        return False, str(e)

def input_validation(patinet_data):
    dict_of_default_values = {
        'age': 25,
        'gender': 'Male',
        'bmi': 25,
        'systolicBp': 80,
        'diastolicBp': 120,
        'heartRate': 90,
        'phsicalActivity': 'Active',
        'smoke': 'No',
        'tobacco': 'No',
        'diet': 'Mix',
        'alcohol': 'No',
        'diabetes': 'No',
        'hypertension': 'No',
        'dyslipidaemia': 'No'
    }

    for key, value in dict_of_default_values.items():

        patinet_data[key] = patinet_data.get(key, value)

        if patinet_data.get(key) == '':
            patinet_data[key] = value
            
    return patinet_data

def aicvd_payload(patient_data):
    return {
        'Id': patient_data['id'],
        'Age': patient_data['age'],
        'Gender': patient_data['gender'],
        'BMI': patient_data['bmi'],
        'BloodPressureDiastolic': patient_data['diastolicBp'],
        'BloodPressureSystolic': patient_data['systolicBp'],
        'HeartRatePerMinute': patient_data['heartRate'],
        'PhysicalActivity': patient_data['phsicalActivity'],
        'Smoke': patient_data['smoke'],
        'Tobacco': patient_data['tobacco'],
        'Diet': patient_data['diet'],
        'Alcohol': patient_data['alcohol'],
        'DiabetesMellitus': patient_data['diabetes'],
        'Hypertension': patient_data['hypertension'],
        'Dyslipidaemia': patient_data['dyslipidaemia']
    }

@app.route('/aicvd', methods=['POST'])
def get_aicvd():
    try:
        patient_data = request.json

        # here we validate the patient data means if patient is not enter the madatory field then we assigned is default value.
        adjusted_patient_data = input_validation(patient_data)

        # here we converted the input obj to required key and value type for aicvd api
        risk_score_payload = aicvd_payload(adjusted_patient_data)

        print(json.dumps(risk_score_payload))

        # headers and api request for aicvd
        headers = {
            'Content-Type': 'application/json',
            'oauth': AICVD_OAUTH_TOKEN
        }
        aicvd_response = requests.post(
            AICVD_URL, 
            headers=headers, 
            data=json.dumps(risk_score_payload)
        )

        if aicvd_response.status_code == 201:
            patient_risk_data = json.loads(aicvd_response.content)

            predicted_data = patient_risk_data.get('Data')[0].get('Prediction')
            heart_risk = predicted_data.get('HeartRisk')

            # token for accessing the report for front end
            # this token patient will get from the apollo 247 end 
            patient_report_access_token = create_access_token (
                identity=patient_risk_data.get('id'),
                expires_delta=timedelta(days=30)
            )
            
            # this obj contains the complect data about use including with timestamp for to in DB
            patient_record_storage_obj = {
                'patient_data': patient_data,
                'patient_risk_data': patient_risk_data,
                'record_id': str(uuid.uuid4()),
                'report_access_token': patient_report_access_token,
                'time_stamp': time.time()
            }

            # this obj contains the required info for front end to patient can see
            filter_patient_risk_data = {
                'risk_status': heart_risk.get('Risk'),
                'risk_score': heart_risk.get('Score'),
                'acceptable_score': heart_risk.get('Acceptable'),
                'top_risks': heart_risk.get('TopRiskContributors')
            }
            
            # headers and api call for data sending to the apollo247
            apollo247_headers = {
                'Content-Type': 'application/json',
                'xauthtoken': APOLLO247_TOKEN
            }
            apollo247_data = {
                'hashId': patient_data.get('id'),
                'recordId': patient_record_storage_obj.get('record_id'),
                'riskCategory': filter_patient_risk_data.get('risk_status'),
                'riskScore': filter_patient_risk_data.get('risk_score'),
                'acceptableScore': filter_patient_risk_data.get('acceptable_score'),
                'reportLink': '{}?recordId={}&token={}'.format(REPORT_URL, patient_record_storage_obj.get('record_id'), patient_report_access_token)
            }

            print(apollo247_data)

            apollo247_response = requests.post(
                APOLLO247_URL,
                headers=apollo247_headers,
                data=json.dumps(apollo247_data)
            )
            print(apollo247_response.content)
            
            # storing the complect data from our db
            insert_data(patient_record_storage_obj, 'aicvd')

            # final resopnse
            response = {
                'status': 'success',
                'response': filter_patient_risk_data
            }
            return make_response(jsonify(response), 200)

        elif aicvd_response.status_code >= 500:
            response = {
                'status': 'error',
                'msg': 'We are experiencing huge load at the movement. Please try again later.'
            }
            return make_response(jsonify(response), 500)

        else:
            response = {
                'status': 'error',
                'api_error_response': json.loads(aicvd_response.content)
            }
            return make_response(jsonify(response), 400)

        
    except Exception as e:
        response = {
            'status': 'error',
            'msg': e
        }
        return make_response(jsonify(response), 400)
        


if __name__ == '__main__':
  CORS(app)
  app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)