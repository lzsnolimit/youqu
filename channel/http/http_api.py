# encoding:utf-8
import base64
import datetime
import json
import time

import jsonpickle
from flask import jsonify
from flask import request, render_template, make_response, session, redirect, Blueprint
from larksuiteoapi import OapiHeader
from larksuiteoapi.card import handle_card
from larksuiteoapi.event import handle_event
from larksuiteoapi.model import OapiRequest
from werkzeug.utils import secure_filename

import common.email
import config
from channel.feishu.common_service import conf
from channel.http import auth
from channel.http.auth import sha256_encrypt, Auth
from common import log
from common.db.dbconfig import db
from common.db.document_record import DocumentRecord
from common.db.user import User
from common.functions import is_valid_password, is_valid_email, is_valid_username, is_valid_phone
from common.generator import generate_uuid
from model import model_factory
from model.azure.azure_model import AZURE
from service.file_training_service import upload_file_service

api = Blueprint('api', __name__)


@api.route("/text", methods=['POST'])
def text():
    user = auth.identify(request)
    if user is None:
        log.INFO("Cookie error")
        return
    data = json.loads(request.data)
    if data:
        msg = data['msg']
        data['uid'] = user.user_id
        request_type = data.get('request_type', "text")
        if not msg:
            return
        reply_text = handle_text(data=data)
        # reply_text="Test reply"
        return {'content': reply_text}


@api.route("/voice", methods=['POST'])
def voice():
    user = auth.identify(request)
    if user is None:
        log.INFO("Cookie error")
        return
    data = json.loads(request.data)
    if data:
        msg = data['msg']
        data['uid'] = user.user_id
        request_type = data.get('request_type', "text")
        if not msg:
            return
        reply_text = handle_text(data=data)
        azure = AZURE()
        audio_data = azure.synthesize_speech(reply_text).audio_data
        audio_base64 = base64.b64encode(audio_data).decode("utf-8")
        response = {
            "audio_data": audio_base64,
            "result": reply_text,
        }
        return jsonify(response)


@api.route("/picture", methods=['POST'])
def picture():
    user = auth.identify(request)
    if user is None:
        log.INFO("Cookie error")
        return
    data = json.loads(request.data)
    if data:
        msg = data['msg']
        data['uid'] = user.user_id
        request_type = data.get('request_type', "text")
        if not msg:
            return
        reply_picture = handle_picture(data=data, user=user)
        response = {
            "picture_data": reply_picture
        }
        return jsonify(response)


# @api.route('/upload', methods=['POST'])
# def upload_file():
#     if 'token' not in request.form:
#         return jsonify({"error": "Token is missing"}), 400
#     token = request.form['token']
#     user = auth.identify(token)
#     if user is None:
#         log.info("Token error")
#         return
#     if len(request.files) <= 0:
#         return jsonify({'content': 'No file selected'}), 400
#
#     file = request.files['files']
#     # 检查文件名是否为空
#     if file.filename == '':
#         return jsonify({'content': 'No file selected'}), 400
#     return upload_file_service(file, user.user_id)


@api.route('/upload', methods=['POST'])
def upload_file():
    token = request.headers.get('Authorization')
    if token is None:
        return jsonify({"error": "Token is missing"}), 400

    user = auth.identify(token)
    if user is None:
        log.info("Token error")
        return jsonify({"error": "Invalid token"}), 403

    if 'file' not in request.files:
        return {"error": "No file in request"}, 400

    file = request.files['file']
    if file.filename == '':
        return {"error": "No file selected"}, 400

    return upload_file_service(file, user)


@api.route("/", methods=['GET'])
def index():
    return render_template('index.html')


@api.route('/register', methods=['POST'])
def register():
    data = json.loads(request.data)
    email = data.get('email', '')
    password = data.get('password', '')
    username = data.get('username', '')
    phone = data.get('phone', '')

    if not (is_valid_email(email) and is_valid_password(password) and is_valid_username(username) and is_valid_phone(
            phone)):
        return jsonify({"error": "Invalid input format"}), 400

    if User.select().where(User.email == email).first() is not None:
        return jsonify({"error": "Email already exists"}), 400
    if User.select().where(User.phone == phone).first() is not None:
        return jsonify({"error": "Phone already exists"}), 400

    current_user = User(user_id=generate_uuid(), user_name=username, email=email, phone=phone,
                        password=sha256_encrypt(password), last_login=datetime.datetime.now(),
                        created_time=datetime.datetime.now(),
                        updated_time=datetime.datetime.now())
    current_user.save()
    # session["user"] = jsonpickle.encode(current_user)
    token = Auth.encode_auth_token(current_user.user_id, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    log.info("Registration success: " + current_user.email)
    return jsonify(
        {"content": "success", "username": current_user.user_name, "token": token, "email": current_user.email,
         "phone": current_user.phone,
         "available_models": current_user.get_available_models()}), 200


##sign out
@api.route("/sign-out", methods=['POST'])
def sign_out():
    token = json.loads(request.data).get('token', '')
    user = auth.identify(token)
    if user is None:
        log.info("Token error")
        return
    model_factory.create_bot(config.conf().get("model").get("type")).clear_session_by_user_id(user.user_id)
    log.info("Login out: ")
    return jsonify({"content": "success"})


@api.route("/login", methods=['POST'])
def login():
    data = json.loads(request.data)
    password = data.get('password', '')
    email = data.get('email', '')
    current_user = auth.authenticate(email, password)
    if current_user is None:
        return jsonify({"error": "Invalid email or password"}), 200
    else:
        # add current user to session
        #        session['user'] = current_user
        token = Auth.encode_auth_token(current_user.user_id, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        log.info("Login success: " + current_user.email)
        return jsonify(
            {"content": "success", "username": current_user.user_name, "user_id": current_user.user_id, "token": token,
             "email": current_user.email,
             "phone": current_user.phone,
             "available_models": current_user.get_available_models()}), 200


@api.route("/login", methods=['get'])
def login_get():
    log.info("Login success: ")
    return redirect('/#/login')


@api.route("/sendcode", methods=['POST'])
def send_code():
    data = json.loads(request.data)
    email = data.get('email', '')
    current_user = User.select().where(User.email == email).first()
    if current_user is None:
        return jsonify({"content": "Reset password email sent"}), 200
    reset_token = Auth.encode_auth_token(current_user.user_id, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), 1)
    # reset_url = f'{channel_conf(const.HTTP).get("domain_name")}={reset_token}'
    common.email.send_reset_password(reset_token, email)
    return jsonify({"message": "Reset password email sent"}), 200


@api.route("/reset_password", methods=['POST'])
def reset_password():
    token = json.loads(request.data).get('token', '')
    current_user = auth.identify(token)
    if current_user is None:
        return jsonify({"error": "Invalid token"}), 401
    data = json.loads(request.data)
    password = data.get('password', '')
    if not is_valid_password(password):
        return jsonify({"error": "Invalid password"}), 400  # bad request
    current_user.password = sha256_encrypt(password)
    current_user.updated_time = datetime.datetime.now()
    current_user.last_login = datetime.datetime.now()
    current_user.save()
    return jsonify({"message": "Reset password success"}), 200


@api.route("/get_user_info", methods=['POST'])
def get_user_info():
    token = json.loads(request.data).get('token', '')
    current_user = auth.identify(token)
    if current_user is None:
        return jsonify({"error": "Invalid user"}), 401
    return jsonify({"username": current_user.user_name, "user_id": current_user.user_id, "email": current_user.email,
                    "phone": current_user.phone,
                    "available_models": current_user.get_available_models(),
                    "available_documents": DocumentRecord.query_all_available_documents(current_user.user_id)}), 200


@api.teardown_request
def teardown_request(exception):
    db.close()


@api.route('/webhook/card', methods=['POST'])
def webhook_card():
    log.info("/webhook/card:" + request.data.decode())
    oapi_request = OapiRequest(uri=request.path, body=request.data, header=OapiHeader(request.headers))
    resp = make_response()
    oapi_resp = handle_card(conf, oapi_request)
    resp.headers['Content-Type'] = oapi_resp.content_type
    resp.data = oapi_resp.body
    resp.status_code = oapi_resp.status_code
    return resp


@api.route('/webhook/event', methods=['GET', 'POST'])
def webhook_event():
    log.info("/webhook/event:" + request.data.decode())
    oapi_request = OapiRequest(uri=request.path, body=request.data, header=OapiHeader(request.headers))
    resp = make_response()
    oapi_resp = handle_event(conf, oapi_request)
    resp.headers['Content-Type'] = oapi_resp.content_type
    resp.data = oapi_resp.body
    resp.status_code = oapi_resp.status_code
    return resp


def handle_text(self, data, user: User):
    context = dict()
    context['user'] = user
    context['conversation_id'] = str(data["conversation_id"])
    return super().build_text_reply_content(data["msg"], context)


def handle_picture(self, data, user: User):
    context = dict()
    context['user'] = user
    return super().build_picture_reply_content(data["msg"])
