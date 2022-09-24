from flask import Flask, jsonify, make_response, request
from flask_cors import CORS
from flask_pymongo import PyMongo
import requests
import json
import uuid
import time
import os

PORT = os.environ.get('PORT')
AICVD_URL = os.environ.get('AICVD_URL')
AICVD_OAUTH_TOKEN = os.environ.get('AICVD_OAUTH_TOKEN')
MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017/bridge_data")

app = Flask(__name__)

app.config["MONGO_URI"] = MONGODB_URL 
mongo = PyMongo(app)
db = mongo.db


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
        'Id': '247-bridge-{}'.format(str(uuid.uuid4())),
        'Age': 25,
        'Gender': 'Male',
        'BMI': 25,
        'BloodPressureDiastolic': 80,
        'BloodPressureSystolic': 120,
        'HeartRatePerMinute': 90,
        'PhysicalActivity': 'Active',
        'Smoke': 'No',
        'Tobacco': 'No',
        'Diet': 'Non-Veg',
        'Alcohol': 'No',
        'DiabetesMellitus': 'No',
        'Hypertension': 'No',
        'Dyslipidaemia': 'No'
    }

    for key, value in dict_of_default_values.items():

        patinet_data[key] = patinet_data.get(key, value)

        if patinet_data.get(key) == '':
            patinet_data[key] = value
            
    return patinet_data

@app.route('/aicvd', methods=['POST'])
def get_aicvd():
    try:
        patient_data = request.json
        patient_data = input_validation(patient_data)

        headers = {
        'Content-Type': 'application/json',
        'oauth': AICVD_OAUTH_TOKEN
        }
        aicvd_response = requests.post(
            AICVD_URL, 
            headers=headers, 
            data=json.dumps(patient_data)
        )

        if aicvd_response.status_code == 201:
            patient_risk_data = json.loads(aicvd_response.content)

            predicted_data = patient_risk_data.get('Data')[0].get('Prediction')
            heart_risk = predicted_data.get('HeartRisk')
            medical_protocol = predicted_data.get('MedicalProtocol')

            diagnostics_and_imaging_recommended = ', '.join(x for x in medical_protocol.get('DiagnosticsAndImagingRecommended') if medical_protocol.get('DiagnosticsAndImagingRecommended')[x] == 'Yes')

            lab_investigation_recommended = ', '.join(x for x in medical_protocol.get('LabInvestigationRecommended') if medical_protocol.get('LabInvestigationRecommended')[x] == 'Yes')

            filter_patient_risk_data = {

                'risk_status': heart_risk.get('Risk'),

                'risk_score': heart_risk.get('Score'),

                'acceptable_score': heart_risk.get('Acceptable'),

                'top_risks': heart_risk.get('TopRiskContributors'),

                'diagnostics_and_imaging_recommended': diagnostics_and_imaging_recommended,

                'lab_investigation_recommended': lab_investigation_recommended,

                'medication': medical_protocol.get('Medication').get('GeneralTreatment'),

                'referral': '{} Referral({})'.format(medical_protocol.get('Referral').get('Department'), medical_protocol.get('Referral').get('Urgency')),

                'general_advice': medical_protocol.get('Management').get('GeneralAdvice'),

                'repeat_visit': medical_protocol.get('Management').get('RepeatVisit').get('Comments')

            }
            patient_record_storage_obj = {
                'record_id': str(uuid.uuid4()),
                'patient_data': patient_data,
                'patient_risk_data': patient_risk_data,
                'time_stamp': time.time()
            }
            insert_data(patient_record_storage_obj, 'aicvd')

            response = {
                'status': 'success',
                'risk_category': 'Category 1' if heart_risk.get('Risk') == 'Low Risk' else 'Category 2',
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
