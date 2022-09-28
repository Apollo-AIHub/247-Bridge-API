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

from dotenv import load_dotenv
load_dotenv()

PORT = os.environ.get('PORT')
AICVD_URL = os.environ.get('AICVD_URL')
AICVD_OAUTH_TOKEN = os.environ.get('AICVD_OAUTH_TOKEN')
APOLLO247_URL = os.environ.get('APOLLO247_URL')
APOLLO247_TOKEN = os.environ.get('APOLLO247_TOKEN')
DB_COLLECTION_NAME = os.environ.get('DB_COLLECTION_NAME')
REPORT_URL = os.environ.get('REPORT_URL')
MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017/bridge_data")
VALIDATE_HASHKEY_TOKEN = os.environ.get("VALIDATE_HASHKEY_TOKEN", "")
APOLLO_VALIDATE_HASHKEY_URL = os.environ.get("APOLLO_VALIDATE_HASHKEY_URL", "")
COUPON = os.environ.get("COUPON", "")
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

def get_data(data, collection_name):
    try:
        print(data)
        return db[collection_name].find_one(data)
    except Exception as e:
        print('---------- Error in find data method ---------')
        print(e)
        print('-------------------')
        return e

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
        'Id': patient_data['hashid'],
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

def validate_id(hashid):
    headers = {
        'Content-Type': 'application/json',
        'xauthtoken': VALIDATE_HASHKEY_TOKEN,
        'hashkey': hashid
    }
    print(headers, APOLLO_VALIDATE_HASHKEY_URL)
    hashid_validity_response = requests.post(
        APOLLO_VALIDATE_HASHKEY_URL, 
        headers=headers
    )
    resp_token_validation = {"status": False, "token": ""}
    hashid_validity_response = json.loads(hashid_validity_response.content)
    if hashid_validity_response.get("token", "") and hashid_validity_response.get("message", "") == "Token generated successfully":
        resp_token_validation["status"] = True
        resp_token_validation["token"]= hashid_validity_response.get("token")
    return resp_token_validation

def send_data_askapollo(patient_data, patient_record_storage_obj, filter_patient_risk_data, patient_report_access_token, token):
    # headers and api call for data sending to the apollo247
    apollo247_headers = {
        'Content-Type': 'application/json',
        'xauthtoken': APOLLO247_TOKEN,
        "Authorization": "Bearer " + token
    }
    apollo247_data = {
        'hashId': patient_data.get('hashid'),
        'recordId': patient_record_storage_obj.get('record_id'),
        'riskCategory': filter_patient_risk_data.get('risk_status'),
        'riskScore': filter_patient_risk_data.get('risk_score'),
        'acceptableScore': filter_patient_risk_data.get('acceptable_score'),
        'reportLink': '{}?recordId={}&token={}'.format(REPORT_URL, patient_record_storage_obj.get('record_id'), patient_report_access_token)

    }

    print(apollo247_data)
    try:
        apollo247_response = requests.post(
            APOLLO247_URL,
            headers=apollo247_headers,
            data=json.dumps(apollo247_data)
        )
        print(apollo247_response.content)
        apollo247_response = json.loads(apollo247_response.content)
    except:
        print("not able to send the record")

    try:
        if apollo247_response:
            apollo247_response["record_id"] = patient_record_storage_obj.get("record_id", "")
            insert_data(apollo247_response, "askapollo-response")
    except:
        print("not able to save the record")
    return apollo247_response

@app.route('/aicvd', methods=['POST'])
def get_aicvd():
    try:
        patient_data = request.json

        ## validate the hashid
        # get the hashid
        hash_id = patient_data.get("hashid","")
        if hash_id:
            hash_id_token_response = validate_id(hash_id)
            print(hash_id_token_response)
            if not hash_id_token_response.get("status", ""):
                response = {
                'status': 'not authenticated',
                'msg': 'We noticed that you are not authenticated.Please go to https://askapollo.com/healthy-heart'
                }
                return make_response(jsonify(response), 200)
            else:
                hash_id_token = hash_id_token_response.get("token","")
        else:
            response = {
                'status': 'not authenticated',
                'msg': 'We noticed that you are not authenticated.Please go to https://askapollo.com/healthy-heart'
            }
            return make_response(jsonify(response), 200)


        # record id for storing unique records
        record_id = str(uuid.uuid4())

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
                identity=record_id,
                expires_delta=timedelta(days=30)
            )

            # this obj contains the complect data about use including with timestamp for to in DB
            patient_record_storage_obj = {
                'patient_data': patient_data,
                'patient_risk_data': patient_risk_data,
                'record_id': record_id,
                'report_access_token': patient_report_access_token,
                'time_stamp': time.time()
            }

            print(patient_report_access_token)

            # this obj contains the required info for front end to patient can see
            filter_patient_risk_data = {
                'risk_status': heart_risk.get('Risk'),
                'risk_score': heart_risk.get('Score'),
                'acceptable_score': heart_risk.get('Acceptable'),
                'top_risks': heart_risk.get('TopRiskContributors')
            }

            ## adding coupon logic only to Moderate and High Risk
            if filter_patient_risk_data.get("risk_status","Low Risk").lower() == "moderate risk" or filter_patient_risk_data.get("risk_status","Low Risk").lower() == "high risk": 
                filter_patient_risk_data["coupon"] = COUPON

            # storing the complect data from our db
            insert_data(patient_record_storage_obj, DB_COLLECTION_NAME)
            
            # @send data to askapollo for crm integration
            send_data_askapollo(patient_data, patient_record_storage_obj, filter_patient_risk_data, patient_report_access_token, hash_id_token)

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
        
@app.route('/aicvd-report', methods=['POST'])
@jwt_required()
def aicvd_report():
    try:
        record_id = request.json.get('record_id')

        complete_patient_data = get_data({'record_id': record_id}, DB_COLLECTION_NAME)

        patient_info = complete_patient_data.get('patient_data')
        patient_risk_info = complete_patient_data.get('patient_risk_data')

        predicted_data = patient_risk_info.get('Data')[0].get('Prediction')
        heart_risk = predicted_data.get('HeartRisk')

        filter_patient_risk_data = {
            'risk_status': heart_risk.get('Risk'),
            'risk_score': heart_risk.get('Score'),
            'acceptable_score': heart_risk.get('Acceptable'),
            'top_risks': heart_risk.get('TopRiskContributors')
        }

        response = {
            'patient_info': patient_info,
            'patient_risk_data': filter_patient_risk_data
        }
        return make_response(jsonify(response), 200)

    except Exception as e:
        response = {
            'status': 'error',
            'msg': e
        }
        return make_response(jsonify(response), 400)



if __name__ == '__main__':
  CORS(app)
  app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
