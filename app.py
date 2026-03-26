from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import io
import zipfile
import openpyxl
import json

app = Flask(__name__)
base_dir = os.path.dirname(__file__)
database_url = os.getenv('DATABASE_URL', f"sqlite:///{os.path.join(base_dir, 'factory.db')}")
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.secret_key = os.getenv('SECRET_KEY', 'factory_parts_secret_key_2024')
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', os.path.join(base_dir, 'uploads'))
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', '0') == '1'

ALLOWED_EXTENSIONS = {'pdf', 'zip', 'rar', '7z'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)


# ==================== 数据模型 ====================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'company' or 'supplier'
    display_name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)


class MachineCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    subcategories = db.relationship('MachineSubcategory', backref='category', lazy=True, cascade='all, delete-orphan')


class MachineSubcategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('machine_category.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    parts = db.relationship('Part', backref='subcategory', lazy=True, cascade='all, delete-orphan')


class Part(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('machine_subcategory.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    pdf_filename = db.Column(db.String(300), nullable=True)
    pdf_original_name = db.Column(db.String(300), nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)       # 发出时间
    completed_at = db.Column(db.DateTime, nullable=True)   # 完成时间
    is_completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    supplier = db.relationship('User', backref='parts', foreign_keys=[supplier_id])

    def elapsed_seconds(self):
        if self.sent_at is None:
            return None
        end = self.completed_at if self.is_completed and self.completed_at else datetime.now()
        sent = self.sent_at
        return int((end - sent).total_seconds())

    def elapsed_str(self):
        secs = self.elapsed_seconds()
        if secs is None:
            return '未发出'
        days = secs // 86400
        hours = (secs % 86400) // 3600
        minutes = (secs % 3600) // 60
        parts = []
        if days:
            parts.append(f'{days}天')
        if hours:
            parts.append(f'{hours}小时')
        parts.append(f'{minutes}分钟')
        return ''.join(parts)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(role=None):
    from functools import wraps
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                flash('请先登录', 'warning')
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('权限不足', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ==================== 初始化数据库 ====================

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(role='company').first():
            admin = User(
                username='JW',
                password_hash=generate_password_hash('353535'),
                role='company',
                display_name='管理公司'
            )
            db.session.add(admin)
            db.session.commit()
        else:
            # 如果已有公司账号但用户名不是JW，更新为JW/353535
            admin = User.query.filter_by(role='company').first()
            if admin.username != 'JW':
                existing_jw = User.query.filter_by(username='JW').first()
                admin.password_hash = generate_password_hash('353535')
                if existing_jw is None or existing_jw.id == admin.id:
                    admin.username = 'JW'
                db.session.commit()


# ==================== 路由：认证 ====================

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session['role'] == 'company':
        return redirect(url_for('company_dashboard'))
    else:
        return redirect(url_for('supplier_dashboard'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['role'] = user.role
            session['display_name'] = user.display_name
            flash(f'欢迎，{user.display_name}！', 'success')
            return redirect(url_for('index'))
        flash('用户名或密码错误', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录', 'info')
    return redirect(url_for('login'))


# ==================== 路由：公司端 ====================

@app.route('/company/dashboard')
@login_required(role='company')
def company_dashboard():
    categories = MachineCategory.query.order_by(MachineCategory.created_at.desc()).all()
    suppliers = User.query.filter_by(role='supplier').all()
    total_parts = Part.query.count()
    sent_parts = Part.query.filter(Part.sent_at.isnot(None)).count()
    completed_parts = Part.query.filter_by(is_completed=True).count()
    return render_template('company_dashboard.html',
                           categories=categories,
                           suppliers=suppliers,
                           total_parts=total_parts,
                           sent_parts=sent_parts,
                           completed_parts=completed_parts)


@app.route('/company/suppliers', methods=['GET', 'POST'])
@login_required(role='company')
def manage_suppliers():
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not display_name or not username or not password:
            flash('请填写完整信息', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('用户名已存在', 'danger')
        else:
            supplier = User(
                username=username,
                password_hash=generate_password_hash(password),
                role='supplier',
                display_name=display_name
            )
            db.session.add(supplier)
            db.session.commit()
            flash(f'供应商 {display_name} 添加成功', 'success')
        return redirect(url_for('manage_suppliers'))
    suppliers = User.query.filter_by(role='supplier').all()
    return render_template('manage_suppliers.html', suppliers=suppliers)


@app.route('/company/suppliers/delete/<int:sid>', methods=['POST'])
@login_required(role='company')
def delete_supplier(sid):
    supplier = User.query.get_or_404(sid)
    if supplier.role != 'supplier':
        flash('操作无效', 'danger')
        return redirect(url_for('manage_suppliers'))
    db.session.delete(supplier)
    db.session.commit()
    flash('供应商已删除', 'success')
    return redirect(url_for('manage_suppliers'))


@app.route('/company/categories', methods=['GET', 'POST'])
@login_required(role='company')
def manage_categories():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('请输入机器大类名称', 'danger')
        else:
            cat = MachineCategory(name=name)
            db.session.add(cat)
            db.session.commit()
            flash(f'机器大类 [{name}] 添加成功', 'success')
        return redirect(url_for('manage_categories'))
    categories = MachineCategory.query.order_by(MachineCategory.created_at.desc()).all()
    return render_template('manage_categories.html', categories=categories)


@app.route('/company/categories/delete/<int:cid>', methods=['POST'])
@login_required(role='company')
def delete_category(cid):
    cat = MachineCategory.query.get_or_404(cid)
    db.session.delete(cat)
    db.session.commit()
    flash('机器大类已删除', 'success')
    return redirect(url_for('manage_categories'))


@app.route('/company/categories/<int:cid>/subcategories', methods=['GET', 'POST'])
@login_required(role='company')
def manage_subcategories(cid):
    cat = MachineCategory.query.get_or_404(cid)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('请输入机械小类名称', 'danger')
        else:
            sub = MachineSubcategory(name=name, category_id=cid)
            db.session.add(sub)
            db.session.commit()
            flash(f'机械小类 [{name}] 添加成功', 'success')
        return redirect(url_for('manage_subcategories', cid=cid))
    return render_template('manage_subcategories.html', category=cat)


@app.route('/company/subcategories/delete/<int:sid>', methods=['POST'])
@login_required(role='company')
def delete_subcategory(sid):
    sub = MachineSubcategory.query.get_or_404(sid)
    cid = sub.category_id
    db.session.delete(sub)
    db.session.commit()
    flash('机械小类已删除', 'success')
    return redirect(url_for('manage_subcategories', cid=cid))


@app.route('/company/subcategories/<int:sub_id>/parts', methods=['GET', 'POST'])
@login_required(role='company')
def manage_parts(sub_id):
    sub = MachineSubcategory.query.get_or_404(sub_id)
    suppliers = User.query.filter_by(role='supplier').all()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_part':
            name = request.form.get('name', '').strip()
            supplier_id = request.form.get('supplier_id') or None
            if not name:
                flash('请输入零件名称', 'danger')
            else:
                pdf_filename = None
                pdf_original_name = None
                if 'pdf_file' in request.files:
                    f = request.files['pdf_file']
                    if f and f.filename and allowed_file(f.filename):
                        orig_name = secure_filename(f.filename)
                        timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
                        save_name = f'{timestamp}_{orig_name}'
                        f.save(os.path.join(app.config['UPLOAD_FOLDER'], save_name))
                        pdf_filename = save_name
                        pdf_original_name = f.filename
                part = Part(
                    name=name,
                    subcategory_id=sub_id,
                    supplier_id=int(supplier_id) if supplier_id else None,
                    pdf_filename=pdf_filename,
                    pdf_original_name=pdf_original_name
                )
                db.session.add(part)
                db.session.commit()
                flash(f'零件 [{name}] 添加成功', 'success')
        elif action == 'import_excel':
            if 'excel_file' not in request.files:
                flash('请选择Excel文件', 'danger')
            else:
                ef = request.files['excel_file']
                if ef and ef.filename:
                    try:
                        wb = openpyxl.load_workbook(ef)
                        ws = wb.active
                        count = 0
                        for row in ws.iter_rows(min_row=2, values_only=True):
                            part_name = str(row[0]).strip() if row[0] else None
                            if part_name and part_name != 'None':
                                part = Part(name=part_name, subcategory_id=sub_id)
                                db.session.add(part)
                                count += 1
                        db.session.commit()
                        flash(f'成功导入 {count} 个零件', 'success')
                    except Exception as e:
                        flash(f'导入失败：{str(e)}', 'danger')
        return redirect(url_for('manage_parts', sub_id=sub_id))

    parts = Part.query.filter_by(subcategory_id=sub_id).order_by(Part.created_at.desc()).all()
    return render_template('manage_parts.html', subcategory=sub, parts=parts, suppliers=suppliers)


@app.route('/company/parts/<int:part_id>/send', methods=['POST'])
@login_required(role='company')
def send_part(part_id):
    part = Part.query.get_or_404(part_id)
    supplier_id = request.form.get('supplier_id')
    if supplier_id:
        part.supplier_id = int(supplier_id)
    if not part.supplier_id:
        flash('请先指定供应商再发出', 'danger')
        return redirect(request.referrer or url_for('company_dashboard'))
    part.sent_at = datetime.now()
    part.is_completed = False
    part.completed_at = None
    db.session.commit()
    flash(f'零件 [{part.name}] 已发出，开始计时', 'success')
    return redirect(request.referrer or url_for('manage_parts', sub_id=part.subcategory_id))


@app.route('/company/parts/<int:part_id>/complete', methods=['POST'])
@login_required(role='company')
def complete_part(part_id):
    part = Part.query.get_or_404(part_id)
    part.is_completed = True
    part.completed_at = datetime.now()
    db.session.commit()
    flash(f'零件 [{part.name}] 已标记为完成', 'success')
    return redirect(request.referrer or url_for('manage_parts', sub_id=part.subcategory_id))


@app.route('/company/parts/<int:part_id>/uncomplete', methods=['POST'])
@login_required(role='company')
def uncomplete_part(part_id):
    part = Part.query.get_or_404(part_id)
    part.is_completed = False
    part.completed_at = None
    db.session.commit()
    flash(f'零件 [{part.name}] 已取消完成状态', 'info')
    return redirect(request.referrer or url_for('manage_parts', sub_id=part.subcategory_id))


@app.route('/company/parts/<int:part_id>/delete', methods=['POST'])
@login_required(role='company')
def delete_part(part_id):
    part = Part.query.get_or_404(part_id)
    sub_id = part.subcategory_id
    if part.pdf_filename:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], part.pdf_filename))
        except OSError:
            pass
    db.session.delete(part)
    db.session.commit()
    flash('零件已删除', 'success')
    return redirect(url_for('manage_parts', sub_id=sub_id))


@app.route('/company/parts/<int:part_id>/upload_pdf', methods=['POST'])
@login_required(role='company')
def upload_pdf(part_id):
    part = Part.query.get_or_404(part_id)
    if 'pdf_file' not in request.files:
        flash('请选择PDF文件', 'danger')
        return redirect(request.referrer)
    f = request.files['pdf_file']
    if not f or not f.filename or not allowed_file(f.filename):
        flash('请上传有效的文件（PDF/ZIP/RAR/7Z）', 'danger')
        return redirect(request.referrer)
    if part.pdf_filename:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], part.pdf_filename))
        except OSError:
            pass
    orig_name = secure_filename(f.filename)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    save_name = f'{timestamp}_{orig_name}'
    f.save(os.path.join(app.config['UPLOAD_FOLDER'], save_name))
    part.pdf_filename = save_name
    part.pdf_original_name = f.filename
    db.session.commit()
    flash('文件上传成功', 'success')
    return redirect(request.referrer)


@app.route('/company/subcategories/<int:sub_id>/upload_zip', methods=['POST'])
@login_required(role='company')
def upload_zip(sub_id):
    sub = MachineSubcategory.query.get_or_404(sub_id)
    if 'zip_file' not in request.files:
        flash('请选择压缩文件', 'danger')
        return redirect(url_for('manage_parts', sub_id=sub_id))
    zf = request.files['zip_file']
    if not zf or not zf.filename:
        flash('请选择压缩文件', 'danger')
        return redirect(url_for('manage_parts', sub_id=sub_id))
    ext = zf.filename.rsplit('.', 1)[-1].lower() if '.' in zf.filename else ''
    if ext != 'zip':
        flash('仅支持 .zip 格式的压缩文件', 'danger')
        return redirect(url_for('manage_parts', sub_id=sub_id))
    parts_list = Part.query.filter_by(subcategory_id=sub_id).all()
    matched = 0
    unmatched_names = []
    try:
        with zipfile.ZipFile(io.BytesIO(zf.read())) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                # 只处理 PDF 文件，防止路径穿越
                raw_name = os.path.basename(info.filename)
                if not raw_name.lower().endswith('.pdf'):
                    continue
                safe_name = secure_filename(raw_name)
                if not safe_name:
                    continue
                # 按文件名（不含扩展名）匹配零件名称
                stem = safe_name.rsplit('.', 1)[0].lower()
                target_part = None
                # 先精确匹配
                for p in parts_list:
                    if p.name.strip().lower() == stem:
                        target_part = p
                        break
                # 再模糊匹配（文件名包含零件名 或 零件名包含文件名）
                if target_part is None:
                    for p in parts_list:
                        pname = p.name.strip().lower()
                        if pname in stem or stem in pname:
                            target_part = p
                            break
                if target_part is None:
                    unmatched_names.append(safe_name)
                    continue
                pdf_data = z.read(info.filename)
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
                save_name = f'{timestamp}_{safe_name}'
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
                with open(save_path, 'wb') as out:
                    out.write(pdf_data)
                # 删除旧图纸文件
                if target_part.pdf_filename:
                    try:
                        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], target_part.pdf_filename))
                    except OSError:
                        pass
                target_part.pdf_filename = save_name
                target_part.pdf_original_name = raw_name
                matched += 1
        db.session.commit()
        msg = f'ZIP 解压完成：成功匹配并上传 {matched} 个图纸'
        if unmatched_names:
            msg += f'，{len(unmatched_names)} 个文件未匹配到零件（{"、".join(unmatched_names[:5])}{"..." if len(unmatched_names) > 5 else ""}）'
        flash(msg, 'success' if matched > 0 else 'warning')
    except zipfile.BadZipFile:
        flash('文件损坏或不是有效的 ZIP 文件', 'danger')
    except Exception as e:
        flash(f'解压失败：{str(e)}', 'danger')
    return redirect(url_for('manage_parts', sub_id=sub_id))


# ==================== 路由：供应商端 ====================

@app.route('/supplier/dashboard')
@login_required(role='supplier')
def supplier_dashboard():
    uid = session['user_id']
    parts = Part.query.filter_by(supplier_id=uid).filter(Part.sent_at.isnot(None)).order_by(Part.sent_at.desc()).all()
    return render_template('supplier_dashboard.html', parts=parts)


# ==================== 路由：文件下载 ====================

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    if 'user_id' not in session:
        flash('请先登录', 'warning')
        return redirect(url_for('login'))
    # 安全检查：只允许访问自己相关的文件
    uid = session['user_id']
    role = session['role']
    part = Part.query.filter_by(pdf_filename=filename).first()
    if part is None:
        return '文件不存在', 404
    if role == 'supplier' and part.supplier_id != uid:
        return '无权访问此文件', 403
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    as_attachment = ext in {'zip', 'rar', '7z'}
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=as_attachment)


# ==================== API：获取零件剩余时间（Ajax刷新） ====================

@app.route('/api/parts/elapsed')
def api_parts_elapsed():
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    uid = session['user_id']
    role = session['role']
    if role == 'supplier':
        parts = Part.query.filter_by(supplier_id=uid).filter(Part.sent_at.isnot(None)).all()
    else:
        parts = Part.query.filter(Part.sent_at.isnot(None)).all()
    data = {}
    for p in parts:
        if not p.is_completed:
            data[p.id] = p.elapsed_str()
    return jsonify(data)


if __name__ == '__main__':
    init_db()
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
    port = int(os.getenv('PORT', '5000'))
    app.run(host='0.0.0.0', debug=debug_mode, port=port)
