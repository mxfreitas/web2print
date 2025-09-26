from flask import Flask, request, render_template, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
import PyPDF2
import fitz  # PyMuPDF para análise de cores
import os
import requests
import uuid
from werkzeug.utils import secure_filename

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
    # Novos campos para análise de cores
    color_type = db.Column(db.String(20), nullable=True)  # 'colorido', 'monocromatico', 'misto'
    color_pages = db.Column(db.Integer, nullable=True)    # número de páginas coloridas
    mono_pages = db.Column(db.Integer, nullable=True)     # número de páginas monocromáticas
    estimated_cost = db.Column(db.Float, nullable=True)   # custo estimado
    
    # Novos campos para configuração avançada de pedidos
    print_type = db.Column(db.String(20), nullable=True)      # 'color', 'mono', 'mixed'
    paper_type = db.Column(db.String(50), nullable=True)      # 'sulfite', 'couche', 'reciclado'
    paper_weight = db.Column(db.Integer, nullable=True)       # gramatura: 75, 90, 120, etc
    binding_type = db.Column(db.String(50), nullable=True)    # 'spiral', 'wire-o', 'capa-dura', 'grampo'
    finishing = db.Column(db.String(100), nullable=True)      # 'laminacao', 'verniz', 'dobra', etc
    copy_quantity = db.Column(db.Integer, nullable=True)      # quantidade de cópias
    total_cost = db.Column(db.Float, nullable=True)           # custo total final
    order_configured = db.Column(db.Boolean, default=False)   # se o pedido foi configurado

db.create_all()

def analyze_pdf_colors(file_path):
    """Analisa cores em um PDF e retorna estatísticas"""
    total_pages = 0  # Inicializar para evitar UnboundLocalError
    try:
        # Abrir o PDF com PyMuPDF
        pdf_document = fitz.open(file_path)
        
        color_pages = 0
        mono_pages = 0
        total_pages = len(pdf_document)
        
        for page_num in range(total_pages):
            page = pdf_document[page_num]
            
            # Verificar imagens na página
            has_color = False
            
            # Verificar texto colorido
            try:
                text_dict = page.get_text("dict")
            except:
                # Se falhar, usar método alternativo
                text_dict = {"blocks": []}
            for block in text_dict["blocks"]:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            # Verificar cor do texto (RGB)
                            color = span.get("color", 0)
                            if color != 0:  # 0 = preto, outros valores = colorido
                                has_color = True
                                break
                        if has_color:
                            break
                    if has_color:
                        break
            
            # Verificar imagens na página
            if not has_color:
                image_list = page.get_images()
                for img_index, img in enumerate(image_list):
                    try:
                        # Extrair dados da imagem
                        xref = img[0]
                        base_image = pdf_document.extract_image(xref)
                        
                        # Verificar se é colorida baseado no espaço de cores
                        colorspace = base_image.get("colorspace", 1)
                        if colorspace == 3:  # RGB colorido
                            has_color = True
                            break
                        elif colorspace == 4:  # CMYK colorido  
                            has_color = True
                            break
                    except:
                        # Se não conseguir analisar a imagem, assumir que pode ser colorida
                        has_color = True
                        break
            
            # Contar páginas
            if has_color:
                color_pages += 1
            else:
                mono_pages += 1
        
        pdf_document.close()
        
        # Determinar tipo geral
        if color_pages == 0:
            color_type = "monocromatico"
        elif mono_pages == 0:
            color_type = "colorido"
        else:
            color_type = "misto"
        
        return {
            "color_type": color_type,
            "color_pages": color_pages,
            "mono_pages": mono_pages,
            "total_pages": total_pages
        }
        
    except Exception as e:
        # Se falhar na análise, tentar obter total de páginas via PyPDF2 como fallback
        try:
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                total_pages = len(pdf_reader.pages)
        except:
            total_pages = 1  # Valor seguro se tudo falhar
        
        # Assumir monocromático como seguro
        return {
            "color_type": "monocromatico", 
            "color_pages": 0,
            "mono_pages": total_pages,
            "total_pages": total_pages
        }

def calculate_estimated_cost(color_pages, mono_pages):
    """Calcula custo estimado baseado na quantidade de páginas (básico)"""
    # Preços básicos exemplo (em reais)
    PRICE_COLOR = 0.50    # R$ 0,50 por página colorida
    PRICE_MONO = 0.10     # R$ 0,10 por página monocromática
    
    color_cost = color_pages * PRICE_COLOR
    mono_cost = mono_pages * PRICE_MONO
    total_cost = color_cost + mono_cost
    
    return round(total_cost, 2)

# Tabelas de preços para configuração avançada
PAPER_PRICES = {
    'sulfite': {
        75: {'color': 0.45, 'mono': 0.08},
        90: {'color': 0.50, 'mono': 0.10}, 
        120: {'color': 0.65, 'mono': 0.15}
    },
    'couche': {
        90: {'color': 0.70, 'mono': 0.20},
        115: {'color': 0.85, 'mono': 0.25},
        150: {'color': 1.10, 'mono': 0.35}
    },
    'reciclado': {
        75: {'color': 0.40, 'mono': 0.07},
        90: {'color': 0.45, 'mono': 0.08}
    }
}

BINDING_PRICES = {
    'grampo': 2.00,
    'spiral': 5.00,
    'wire-o': 8.00,
    'capa-dura': 25.00
}

FINISHING_PRICES = {
    'laminacao': 3.00,
    'verniz': 2.50,
    'dobra': 1.50,
    'perfuracao': 1.00
}

def calculate_advanced_cost(color_pages, mono_pages, paper_type='sulfite', 
                          paper_weight=90, binding_type='grampo', 
                          finishing=None, copy_quantity=1):
    """Calcula custo avançado baseado em todas as configurações"""
    
    # Validar se o tipo de papel e gramatura existem
    if paper_type not in PAPER_PRICES:
        paper_type = 'sulfite'
    
    if paper_weight not in PAPER_PRICES[paper_type]:
        # Usar gramatura mais próxima disponível
        available_weights = list(PAPER_PRICES[paper_type].keys())
        paper_weight = min(available_weights, key=lambda x: abs(x - paper_weight))
    
    # Preços por página baseados no papel
    page_prices = PAPER_PRICES[paper_type][paper_weight]
    
    # Calcular custo das páginas
    pages_cost = (color_pages * page_prices['color']) + (mono_pages * page_prices['mono'])
    
    # Adicionar custo de encadernação
    binding_cost = BINDING_PRICES.get(binding_type, 0)
    
    # Adicionar custo de acabamento
    finishing_cost = 0
    if finishing:
        finishing_options = finishing.split(',')
        for option in finishing_options:
            option = option.strip()
            finishing_cost += FINISHING_PRICES.get(option, 0)
    
    # Custo por exemplar
    cost_per_copy = pages_cost + binding_cost + finishing_cost
    
    # Custo total considerando quantidade
    total_cost = cost_per_copy * copy_quantity
    
    return {
        'pages_cost': round(pages_cost, 2),
        'binding_cost': round(binding_cost, 2),
        'finishing_cost': round(finishing_cost, 2),
        'cost_per_copy': round(cost_per_copy, 2),
        'total_cost': round(total_cost, 2),
        'copy_quantity': copy_quantity
    }

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

            # Ler o PDF e contar páginas com tratamento robusto
            try:
                # Primeira tentativa: ler diretamente do stream
                file.stream.seek(0)  # Garantir que está no início
                
                # Verificar se o arquivo começa com header PDF válido
                header = file.stream.read(8)
                if not header.startswith(b'%PDF-'):
                    return jsonify({'error': 'Arquivo não é um PDF válido'}), 400
                
                # Voltar ao início para leitura completa
                file.stream.seek(0)
                
                # Tentar ler com PyPDF2
                pdf_reader = PyPDF2.PdfReader(file.stream)
                num_pages = len(pdf_reader.pages)
                
            except Exception as pdf_error:
                # Se falhar, tentar método alternativo salvando temporariamente
                try:
                    # Salvar temporariamente para leitura
                    file.stream.seek(0)
                    temp_path = os.path.join('uploads', f'temp_{file.filename}')
                    file.save(temp_path)
                    
                    # Tentar ler do arquivo salvo
                    with open(temp_path, 'rb') as temp_file:
                        pdf_reader = PyPDF2.PdfReader(temp_file)
                        num_pages = len(pdf_reader.pages)
                    
                    # Remover arquivo temporário
                    os.remove(temp_path)
                    
                except Exception:
                    return jsonify({'error': 'PDF corrompido ou inválido. Tente outro arquivo.'}), 400

            # Gerar nome seguro para o arquivo
            secure_name = secure_filename(file.filename)
            if not secure_name:
                secure_name = f"arquivo_{uuid.uuid4().hex}.pdf"
            
            # Garantir extensão .pdf
            if not secure_name.lower().endswith('.pdf'):
                secure_name = f"{secure_name}.pdf"
            
            # Salvar o arquivo primeiro para análise
            file.stream.seek(0)  # Voltar ao início do stream
            file_path = os.path.join('uploads', secure_name)
            file.save(file_path)

            # Analisar cores do PDF
            color_stats = analyze_pdf_colors(file_path)
            estimated_cost = calculate_estimated_cost(color_stats['color_pages'], color_stats['mono_pages'])

            # Atualizar informações do usuário com dados de cor
            user.uploaded_file = secure_name
            user.num_pages = num_pages
            user.color_type = color_stats['color_type']
            user.color_pages = color_stats['color_pages']
            user.mono_pages = color_stats['mono_pages'] 
            user.estimated_cost = estimated_cost
            db.session.commit()

            return jsonify({
                'pages': num_pages,
                'color_type': color_stats['color_type'],
                'color_pages': color_stats['color_pages'],
                'mono_pages': color_stats['mono_pages'],
                'estimated_cost': estimated_cost,
                'redirect_to_configure': True
            })
            
        except Exception as e:
            return jsonify({'error': f'Erro ao processar arquivo: {str(e)}'}), 500

    return render_template('upload.html')

@app.route('/configure', methods=['GET', 'POST'])
def configure():
    if 'cpf' not in session:
        return redirect(url_for('register'))

    user = User.query.filter_by(cpf=session['cpf']).first()
    if not user or not user.uploaded_file:
        return redirect(url_for('upload'))

    if request.method == 'POST':
        try:
            # Obter configurações do formulário
            print_type = request.form.get('print_type', 'mixed')
            paper_type = request.form.get('paper_type', 'sulfite')
            paper_weight = int(request.form.get('paper_weight', 90))
            binding_type = request.form.get('binding_type', 'grampo')
            finishing = request.form.get('finishing', '')
            copy_quantity = int(request.form.get('copy_quantity', 1))

            # Calcular páginas baseado no tipo de impressão escolhido
            if print_type == 'color':
                # Imprimir tudo em cores
                color_pages_final = user.color_pages + user.mono_pages
                mono_pages_final = 0
            elif print_type == 'mono':
                # Imprimir tudo em monocromático
                color_pages_final = 0
                mono_pages_final = user.color_pages + user.mono_pages
            else:  # mixed
                # Manter separação original
                color_pages_final = user.color_pages
                mono_pages_final = user.mono_pages

            # Calcular custo avançado
            cost_details = calculate_advanced_cost(
                color_pages_final, mono_pages_final,
                paper_type, paper_weight, binding_type,
                finishing if finishing else None, copy_quantity
            )

            # Atualizar configurações do usuário
            user.print_type = print_type
            user.paper_type = paper_type
            user.paper_weight = paper_weight
            user.binding_type = binding_type
            user.finishing = finishing if finishing else None
            user.copy_quantity = copy_quantity
            user.total_cost = cost_details['total_cost']
            user.order_configured = True
            
            db.session.commit()

            return redirect(url_for('cart'))

        except Exception as e:
            return render_template('configure.html', user=user, error=f'Erro ao salvar configuração: {str(e)}')

    return render_template('configure.html', user=user)

@app.route('/cart')
def cart():
    if 'cpf' not in session:
        return redirect(url_for('register'))

    user = User.query.filter_by(cpf=session['cpf']).first()
    
    if not user or not user.uploaded_file:
        return render_template('cart.html', 
                             error="Nenhum arquivo foi enviado ainda. Faça o upload primeiro.")
    
    # Preparar dados para o template
    cart_data = {
        'filename': user.uploaded_file,
        'num_pages': user.num_pages or 0,
        'color_type': user.color_type or 'monocromatico',
        'color_pages': user.color_pages or 0,
        'mono_pages': user.mono_pages or 0,
        'estimated_cost': user.estimated_cost or 0.0
    }
    
    return render_template('cart.html', **cart_data)

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run(host='0.0.0.0', port=5000, debug=True)
