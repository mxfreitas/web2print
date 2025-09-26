from flask import Flask, request, render_template, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
import PyPDF2
import os
import requests

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'web2print-secret-key-2024-replit-env'  # Chave secreta configurada

# Configurações de sessão
app.config['SESSION_COOKIE_SECURE'] = False  # Para desenvolvimento
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutos

db = SQLAlchemy(app)
app.app_context().push()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    cpf = db.Column(db.String(14), unique=True, nullable=False)
    address = db.Column(db.String(200), nullable=False)
    cep = db.Column(db.String(10), nullable=False)
    uploaded_file = db.Column(db.String(200), nullable=True)
    num_pages = db.Column(db.Integer, nullable=True)

db.create_all()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/users')
def users():
    all_users = User.query.all()  # Obtém todos os usuários
    return render_template('users.html', users=all_users)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            cpf = request.form.get('cpf', '').strip()
            cep = request.form.get('cep', '').strip()

            # Validar campos obrigatórios
            if not name or not cpf or not cep:
                return render_template('register.html', error='Todos os campos são obrigatórios')

            # Verificar se o CPF já existe
            existing_user = User.query.filter_by(cpf=cpf).first()
            if existing_user:
                return render_template('register.html', error='CPF já cadastrado')

            # Buscar endereço a partir do CEP
            try:
                response = requests.get(f'https://viacep.com.br/ws/{cep}/json/', timeout=10)
                response.raise_for_status()
                address_data = response.json()
            except requests.exceptions.RequestException:
                return render_template('register.html', error='Erro ao consultar CEP. Tente novamente.')

            if 'erro' in address_data:
                return render_template('register.html', error='CEP inválido')

            # Verificar se todos os campos do endereço estão presentes
            required_fields = ['logradouro', 'bairro', 'localidade', 'uf']
            if not all(field in address_data and address_data[field] for field in required_fields):
                return render_template('register.html', error='CEP retornou dados incompletos')

            address = f"{address_data['logradouro']}, {address_data['bairro']}, {address_data['localidade']} - {address_data['uf']}"

            # Criar e salvar usuário
            new_user = User(name=name, cpf=cpf, address=address, cep=cep)
            db.session.add(new_user)
            db.session.commit()
            
            # Configurar sessão
            session['cpf'] = cpf
            session.permanent = True
            
            return redirect(url_for('upload'))
            
        except Exception as e:
            db.session.rollback()
            return render_template('register.html', error=f'Erro interno: {str(e)}')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cpf = request.form.get('cpf', '').strip()
        
        if not cpf:
            return render_template('login.html', error='CPF é obrigatório')
        
        # Verificar se o usuário existe
        user = User.query.filter_by(cpf=cpf).first()
        if not user:
            return render_template('login.html', error='CPF não encontrado. Faça seu cadastro primeiro.')
        
        # Configurar sessão e redirecionar
        session['cpf'] = cpf
        session.permanent = True
        return redirect(url_for('upload'))
    
    return render_template('login.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'cpf' not in session:
        return redirect(url_for('register'))

    if request.method == 'POST':
        try:
            # Verificar se o arquivo foi enviado
            if 'file' not in request.files:
                return jsonify({'error': 'Nenhum arquivo foi enviado'}), 400
            
            file = request.files['file']
            
            # Verificar se um arquivo foi selecionado
            if file.filename == '' or file.filename is None:
                return jsonify({'error': 'Nenhum arquivo foi selecionado'}), 400
            
            # Verificar se é um arquivo PDF
            if not file.filename.lower().endswith('.pdf'):
                return jsonify({'error': 'Apenas arquivos PDF são aceitos'}), 400

            # Buscar o usuário na sessão
            user = User.query.filter_by(cpf=session['cpf']).first()
            if not user:
                return jsonify({'error': 'Usuário não encontrado. Faça o registro novamente.'}), 400

            # Ler o PDF e contar páginas
            pdf_reader = PyPDF2.PdfReader(file.stream)
            num_pages = len(pdf_reader.pages)

            # Atualizar informações do usuário
            user.uploaded_file = file.filename
            user.num_pages = num_pages
            db.session.commit()

            # Salvar o arquivo
            file.stream.seek(0)  # Voltar ao início do stream
            file.save(os.path.join('uploads', file.filename))

            return jsonify({'pages': num_pages})
            
        except Exception as e:
            return jsonify({'error': f'Erro ao processar arquivo: {str(e)}'}), 500

    return render_template('upload.html')

@app.route('/cart')
def cart():
    if 'cpf' not in session:
        return redirect(url_for('register'))

    user = User.query.filter_by(cpf=session['cpf']).first()
    num_pages = user.num_pages if user else 0
    return render_template('cart.html', num_pages=num_pages)

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run(host='0.0.0.0', port=5000, debug=True)
