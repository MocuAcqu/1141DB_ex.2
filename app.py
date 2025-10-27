import os
import csv  
import io   
from werkzeug.utils import secure_filename 
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId

load_dotenv()

app = Flask(__name__)

app.config["MONGO_URI"] = os.getenv("MONGO_URI")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

mongo = PyMongo(app)

ALLOWED_EXTENSIONS = {'csv'}
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('profile'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # 從表單接收資料
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')

        if not name or not email or not password or not role:
            flash("所有欄位都是必填的！")
            return redirect(url_for('register'))

        # 檢查信箱是否已被註冊
        existing_user = mongo.db.users.find_one({'email': email})
        if existing_user:
            flash("這個信箱已經被註冊過了！")
            return redirect(url_for('register'))

        # 將密碼進行雜湊處理
        hashed_password = generate_password_hash(password)

        # 將新使用者資料存入資料庫
        mongo.db.users.insert_one({
            'name': name,
            'email': email,
            'password': hashed_password,
            'role': role
        })

        flash("註冊成功！請登入。")
        return redirect(url_for('login'))

    # 如果是 GET 請求，就顯示註冊頁面
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # 根據 email 尋找使用者
        user = mongo.db.users.find_one({'email': email})

        # 檢查使用者是否存在，且密碼是否正確
        if user and check_password_hash(user['password'], password):
            # 登入成功，將使用者資訊存入 session
            session['user_id'] = str(user['_id']) 
            session['name'] = user['name']
            session['role'] = user['role']
            flash("登入成功！")
            return redirect(url_for('profile'))
        else:
            flash("信箱或密碼錯誤！")
            return redirect(url_for('login'))

    # 如果是 GET 請求，就顯示登入頁面
    return render_template('login.html')

# 個人資料頁面 (需要登入才能訪問)
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        flash("請先登入！")
        return redirect(url_for('login'))

    # 根據不同身分，從資料庫讀取不同的活動資料
    if session['role'] == 'organizer':
        user_id_obj = ObjectId(session['user_id'])
        my_events = list(mongo.db.events.find({'organizer_id': user_id_obj}))
        return render_template('profile.html', my_events=my_events)
    else:
        all_events = list(mongo.db.events.find({}))
        return render_template('profile.html', all_events=all_events)

@app.route('/logout', methods=['GET'])
def show_logout_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('logout.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash("您已成功登出。")
    return redirect(url_for('login'))

@app.route('/create_event', methods=['POST'])
def create_event():
    if 'user_id' not in session or session.get('role') != 'organizer':
        flash("權限不足！")
        return redirect(url_for('profile'))

    event_name = request.form.get('event_name')
    description = request.form.get('description')
    event_time = request.form.get('event_time')
    location = request.form.get('location')

    if not all([event_name, description, event_time, location]):
        flash("所有欄位都是必填的！")
        return redirect(url_for('profile'))

    mongo.db.events.insert_one({
        'organizer_id': ObjectId(session['user_id']),
        'organizer_name': session['name'],
        'name': event_name,
        'description': description,
        'time': event_time,
        'location': location,
        'current_number': 0,
        'queue': []
    })

    flash("活動建立成功！")
    return redirect(url_for('profile'))

@app.route('/create_events_bulk', methods=['POST'])
def create_events_bulk():
    if 'user_id' not in session or session.get('role') != 'organizer':
        return redirect(url_for('login'))

    # 使用 getlist() 獲取所有同名欄位的值
    names = request.form.getlist('event_name[]')
    descriptions = request.form.getlist('description[]')
    times = request.form.getlist('event_time[]')
    locations = request.form.getlist('location[]')

    events_to_insert = []
    # 使用 zip 將多個列表組合成一個個的活動
    for name, desc, time, loc in zip(names, descriptions, times, locations):
        if name and desc and time and loc: # 確保所有欄位都有值
            event_doc = {
                'organizer_id': ObjectId(session['user_id']),
                'organizer_name': session['name'],
                'name': name,
                'description': desc,
                'time': time,
                'location': loc,
                'current_number': 0,
                'queue': []
            }
            events_to_insert.append(event_doc)

    if events_to_insert:
        mongo.db.events.insert_many(events_to_insert)
        flash(f"成功新增 {len(events_to_insert)} 筆活動！")
    else:
        flash("沒有有效的活動資料可以新增。")
    
    return redirect(url_for('profile'))


# 處理從 CSV 檔案匯入活動
@app.route('/import_events_csv', methods=['POST'])
def import_events_csv():
    if 'user_id' not in session or session.get('role') != 'organizer':
        return redirect(url_for('login'))

    if 'csv_file' not in request.files:
        flash('請求中沒有檔案部分')
        return redirect(url_for('profile'))
    
    file = request.files['csv_file']

    if file.filename == '':
        flash('沒有選擇檔案')
        return redirect(url_for('profile'))

    if file and allowed_file(file.filename):
        try:
            # 為了能正確讀取中文，需要將檔案內容解碼為 utf-8
            file_stream = io.TextIOWrapper(file.stream, 'utf-8')
            # 使用 DictReader 可以讓我們用標頭名稱來讀取資料
            csv_reader = csv.DictReader(file_stream)
            
            events_to_insert = []
            for row in csv_reader:
                # 檢查必要的欄位是否存在
                if all(key in row for key in ['name', 'description', 'time', 'location']):
                    event_doc = {
                        'organizer_id': ObjectId(session['user_id']),
                        'organizer_name': session['name'],
                        'name': row['name'],
                        'description': row['description'],
                        'time': row['time'],
                        'location': row['location'],
                        'current_number': 0,
                        'queue': []
                    }
                    events_to_insert.append(event_doc)
            
            if events_to_insert:
                mongo.db.events.insert_many(events_to_insert)
                flash(f"成功從 CSV 匯入 {len(events_to_insert)} 筆活動！")
            else:
                flash("CSV 檔案中沒有有效的活動資料或格式不符。")

        except Exception as e:
            flash(f"處理檔案時發生錯誤: {e}")
            return redirect(url_for('profile'))
    else:
        flash("只允許上傳 CSV 格式的檔案！")

    return redirect(url_for('profile'))

if __name__ == '__main__':
    app.run(debug=True)