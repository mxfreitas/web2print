from flask import Flask, request, render_template, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
import PyPDF2
import os
import requests

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your_secret_key'  # Mude isso para uma chave secreta real
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
        name = request.form['name']
        cpf = request.form['cpf']
        cep = request.form['cep']

        # Verificar se o CPF já existe
        existing_user = User.query.filter_by(cpf=cpf).first()
        if existing_user:
            return render_template('register.html', error='CPF já cadastrado')

        # Buscar endereço a partir do CEP
        response = requests.get(f'https://viacep.com.br/ws/{cep}/json/')
        address_data = response.json()

        if 'erro' in address_data:
            return render_template('register.html', error='CEP inválido')

        address = f"{address_data['logradouro']}, {address_data['bairro']}, {address_data['localidade']} - {address_data['uf']}"

        new_user = User(name=name, cpf=cpf, address=address, cep=cep)
        db.session.add(new_user)
        db.session.commit()
        session['cpf'] = cpf
        return redirect(url_for('upload'))
    
    return render_template('register.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'cpf' not in session:
        return redirect(url_for('register'))

    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.pdf'):
            pdf_reader = PyPDF2.PdfReader(file)
            num_pages = len(pdf_reader.pages)

            user = User.query.filter_by(cpf=session['cpf']).first()
            user.uploaded_file = file.filename
            user.num_pages = num_pages
            db.session.commit()

            # Salvar o arquivo
            file.save(os.path.join('uploads', file.filename))

            return jsonify({'pages': num_pages})
        else:
            return jsonify({'error': 'Invalid file type'}), 400

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
