from flask import Flask, request, render_template, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
import PyPDF2
import fitz  # PyMuPDF para análise de cores
import os
import requests
import uuid
import hashlib
from werkzeug.utils import secure_filename
from functools import wraps

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

class PaperType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # 'sulfite', 'couche', 'reciclado'
    display_name = db.Column(db.String(100), nullable=False)      # 'Sulfite', 'Couchê', 'Reciclado'
    description = db.Column(db.String(200), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    # Relacionamento com gramaturas
    weights = db.relationship('PaperWeight', backref='paper_type', lazy=True, cascade="all, delete-orphan")

class PaperWeight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    paper_type_id = db.Column(db.Integer, db.ForeignKey('paper_type.id'), nullable=False)
    weight = db.Column(db.Integer, nullable=False)  # 75, 90, 120, etc.
    price_color = db.Column(db.Float, nullable=False)  # preço por página colorida
    price_mono = db.Column(db.Float, nullable=False)   # preço por página monocromática
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    # Índice único por tipo de papel + gramatura
    __table_args__ = (db.UniqueConstraint('paper_type_id', 'weight', name='unique_paper_weight'),)

class BindingType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # 'grampo', 'spiral', etc.
    display_name = db.Column(db.String(100), nullable=False)      # 'Grampo', 'Espiral', etc.
    description = db.Column(db.String(200), nullable=True)
    price = db.Column(db.Float, nullable=False)  # preço da encadernação
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

class FinishingType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # 'laminacao', 'verniz', etc.
    display_name = db.Column(db.String(100), nullable=False)      # 'Laminação', 'Verniz', etc.
    description = db.Column(db.String(200), nullable=True)
    price = db.Column(db.Float, nullable=False)  # preço do acabamento
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

# Modelo para controle administrativo simples
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)  # Hash da senha
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

db.create_all()

# Função para popular dados iniciais no banco
def populate_initial_data():
    """Popula dados iniciais dos preços no banco de dados"""
    
    # Verificar se já existem dados
    if PaperType.query.count() > 0:
        return  # Dados já existem
    
    try:
        # Dados dos papéis baseados no PAPER_PRICES
        paper_data = [
            {
                'name': 'sulfite',
                'display_name': 'Sulfite',
                'description': 'Papel padrão para impressão',
                'weights': [
                    {'weight': 75, 'price_color': 0.45, 'price_mono': 0.08},
                    {'weight': 90, 'price_color': 0.50, 'price_mono': 0.10},
                    {'weight': 120, 'price_color': 0.65, 'price_mono': 0.15}
                ]
            },
            {
                'name': 'couche',
                'display_name': 'Couchê',
                'description': 'Papel brilhante para impressão de qualidade',
                'weights': [
                    {'weight': 90, 'price_color': 0.70, 'price_mono': 0.20},
                    {'weight': 115, 'price_color': 0.85, 'price_mono': 0.25},
                    {'weight': 150, 'price_color': 1.10, 'price_mono': 0.35}
                ]
            },
            {
                'name': 'reciclado',
                'display_name': 'Reciclado',
                'description': 'Papel ecológico reciclado',
                'weights': [
                    {'weight': 75, 'price_color': 0.40, 'price_mono': 0.07},
                    {'weight': 90, 'price_color': 0.45, 'price_mono': 0.08}
                ]
            }
        ]
        
        # Criar tipos de papel
        for paper_info in paper_data:
            paper_type = PaperType(
                name=paper_info['name'],
                display_name=paper_info['display_name'],
                description=paper_info['description']
            )
            db.session.add(paper_type)
            db.session.flush()  # Para obter o ID
            
            # Criar gramaturas para este papel
            for weight_info in paper_info['weights']:
                weight = PaperWeight(
                    paper_type_id=paper_type.id,
                    weight=weight_info['weight'],
                    price_color=weight_info['price_color'],
                    price_mono=weight_info['price_mono']
                )
                db.session.add(weight)
        
        # Dados de encadernação baseados no BINDING_PRICES
        binding_data = [
            {'name': 'grampo', 'display_name': 'Grampo (2 grampos)', 'price': 2.00, 'description': 'Encadernação simples com 2 grampos'},
            {'name': 'spiral', 'display_name': 'Espiral plástica', 'price': 5.00, 'description': 'Encadernação com espiral plástica'},
            {'name': 'wire-o', 'display_name': 'Wire-o (espiral metálica)', 'price': 8.00, 'description': 'Encadernação com espiral metálica'},
            {'name': 'capa-dura', 'display_name': 'Capa dura', 'price': 25.00, 'description': 'Encadernação em capa dura'}
        ]
        
        for binding_info in binding_data:
            binding = BindingType(
                name=binding_info['name'],
                display_name=binding_info['display_name'],
                description=binding_info['description'],
                price=binding_info['price']
            )
            db.session.add(binding)
        
        # Dados de acabamento baseados no FINISHING_PRICES
        finishing_data = [
            {'name': 'laminacao', 'display_name': 'Laminação', 'price': 3.00, 'description': 'Laminação plástica'},
            {'name': 'verniz', 'display_name': 'Verniz', 'price': 2.50, 'description': 'Aplicação de verniz'},
            {'name': 'dobra', 'display_name': 'Dobra', 'price': 1.50, 'description': 'Dobra no papel'},
            {'name': 'perfuracao', 'display_name': 'Perfuração', 'price': 1.00, 'description': 'Perfuração para arquivo'}
        ]
        
        for finishing_info in finishing_data:
            finishing = FinishingType(
                name=finishing_info['name'],
                display_name=finishing_info['display_name'],
                description=finishing_info['description'],
                price=finishing_info['price']
            )
            db.session.add(finishing)
        
        # Criar admin padrão (senha: admin123)
        import hashlib
        admin_password = hashlib.sha256("admin123".encode()).hexdigest()
        admin_user = Admin(
            username="admin",
            password_hash=admin_password
        )
        db.session.add(admin_user)
        
        db.session.commit()
        print("✅ Dados iniciais inseridos no banco de dados!")
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erro ao inserir dados iniciais: {str(e)}")

# Popular dados iniciais na inicialização
populate_initial_data()

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
    """Calcula custo avançado baseado nos dados do banco de dados"""
    
    try:
        # Buscar preço do papel
        paper_type_obj = PaperType.query.filter_by(name=paper_type, active=True).first()
        if not paper_type_obj:
            # Fallback para sulfite se não encontrar
            paper_type_obj = PaperType.query.filter_by(name='sulfite', active=True).first()
        
        if not paper_type_obj:
            # Fallback final usando preços hardcoded se não houver dados no banco
            return calculate_advanced_cost_fallback(color_pages, mono_pages, paper_type, 
                                                 paper_weight, binding_type, finishing, copy_quantity)
        
        # Buscar gramatura específica
        paper_weight_obj = PaperWeight.query.filter_by(
            paper_type_id=paper_type_obj.id, 
            weight=paper_weight,
            active=True
        ).first()
        
        if not paper_weight_obj:
            # Buscar gramatura mais próxima
            available_weights = PaperWeight.query.filter_by(
                paper_type_id=paper_type_obj.id,
                active=True
            ).all()
            
            if available_weights:
                paper_weight_obj = min(available_weights, 
                                     key=lambda x: abs(x.weight - paper_weight))
        
        if not paper_weight_obj:
            return calculate_advanced_cost_fallback(color_pages, mono_pages, paper_type, 
                                                 paper_weight, binding_type, finishing, copy_quantity)
        
        # Calcular custo das páginas
        pages_cost = (color_pages * paper_weight_obj.price_color) + (mono_pages * paper_weight_obj.price_mono)
        
        # Buscar custo de encadernação
        binding_obj = BindingType.query.filter_by(name=binding_type, active=True).first()
        binding_cost = binding_obj.price if binding_obj else 0
        
        # Calcular custo de acabamento
        finishing_cost = 0
        if finishing:
            finishing_options = finishing.split(',')
            for option in finishing_options:
                option = option.strip()
                finishing_obj = FinishingType.query.filter_by(name=option, active=True).first()
                if finishing_obj:
                    finishing_cost += finishing_obj.price
        
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
        
    except Exception as e:
        print(f"Erro no cálculo avançado: {str(e)}")
        # Fallback para função com preços hardcoded
        return calculate_advanced_cost_fallback(color_pages, mono_pages, paper_type, 
                                             paper_weight, binding_type, finishing, copy_quantity)

def calculate_advanced_cost_fallback(color_pages, mono_pages, paper_type='sulfite', 
                                   paper_weight=90, binding_type='grampo', 
                                   finishing=None, copy_quantity=1):
    """Função de fallback usando preços hardcoded (compatibilidade)"""
    
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

# ============================================
# SISTEMA ADMINISTRATIVO
# ============================================

def admin_required(f):
    """Decorator para verificar autenticação administrativa"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            flash('Acesso negado. Faça login como administrador.', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def get_admin_stats():
    """Calcula estatísticas para o dashboard administrativo"""
    try:
        total_users = User.query.count()
        total_uploads = User.query.filter(User.uploaded_file.isnot(None)).count()
        
        # Calcular receita total (usuários com pedidos configurados)
        users_with_orders = User.query.filter(
            User.order_configured == True,
            User.total_cost.isnot(None)
        ).all()
        
        total_revenue = sum(user.total_cost for user in users_with_orders if user.total_cost)
        average_order = total_revenue / len(users_with_orders) if users_with_orders else 0
        
        # Estatísticas de papel mais usado
        paper_usage = {}
        for user in users_with_orders:
            if user.paper_type:
                paper_usage[user.paper_type] = paper_usage.get(user.paper_type, 0) + 1
        
        most_used_paper = max(paper_usage.items(), key=lambda x: x[1]) if paper_usage else ('N/A', 0)
        
        return {
            'total_users': total_users,
            'total_uploads': total_uploads,
            'total_orders': len(users_with_orders),
            'total_revenue': round(total_revenue, 2),
            'average_order': round(average_order, 2),
            'most_used_paper': most_used_paper[0],
            'conversion_rate': round((len(users_with_orders) / total_users * 100) if total_users > 0 else 0, 1)
        }
    except Exception as e:
        print(f"Erro ao calcular estatísticas: {str(e)}")
        return {
            'total_users': 0, 'total_uploads': 0, 'total_orders': 0,
            'total_revenue': 0, 'average_order': 0, 'most_used_paper': 'N/A',
            'conversion_rate': 0
        }

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('Usuário e senha são obrigatórios', 'error')
            return render_template('admin_login.html')
        
        # Hash da senha fornecida
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # Verificar credenciais
        admin = Admin.query.filter_by(username=username, password_hash=password_hash, active=True).first()
        
        if admin:
            session['admin_logged_in'] = True
            session['admin_username'] = username
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Credenciais inválidas', 'error')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    flash('Logout realizado com sucesso!', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = get_admin_stats()
    recent_users = User.query.order_by(User.id.desc()).limit(5).all()
    return render_template('admin_dashboard.html', stats=stats, recent_users=recent_users)

# ============================================
# CRUD ADMINISTRATIVO - TIPOS DE PAPEL
# ============================================

@app.route('/admin/papers')
@admin_required
def admin_papers():
    papers = PaperType.query.all()
    return render_template('admin_papers.html', papers=papers)

@app.route('/admin/papers/create', methods=['GET', 'POST'])
@admin_required
def admin_papers_create():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            display_name = request.form.get('display_name', '').strip()
            description = request.form.get('description', '').strip()
            
            if not name or not display_name:
                flash('Nome e nome de exibição são obrigatórios', 'error')
                return render_template('admin_paper_form.html')
            
            # Verificar se já existe
            existing = PaperType.query.filter_by(name=name).first()
            if existing:
                flash('Já existe um tipo de papel com esse nome', 'error')
                return render_template('admin_paper_form.html')
            
            # Criar novo tipo de papel
            paper_type = PaperType(
                name=name,
                display_name=display_name,
                description=description
            )
            db.session.add(paper_type)
            db.session.commit()
            
            flash('Tipo de papel criado com sucesso!', 'success')
            return redirect(url_for('admin_papers'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar tipo de papel: {str(e)}', 'error')
    
    return render_template('admin_paper_form.html')

@app.route('/admin/papers/<int:paper_id>/weights')
@admin_required
def admin_paper_weights(paper_id):
    paper = PaperType.query.get_or_404(paper_id)
    weights = PaperWeight.query.filter_by(paper_type_id=paper_id).all()
    return render_template('admin_paper_weights.html', paper=paper, weights=weights)

@app.route('/admin/papers/<int:paper_id>/weights/create', methods=['GET', 'POST'])
@admin_required
def admin_paper_weights_create(paper_id):
    paper = PaperType.query.get_or_404(paper_id)
    
    if request.method == 'POST':
        try:
            weight = request.form.get('weight', type=int)
            price_color = request.form.get('price_color', type=float)
            price_mono = request.form.get('price_mono', type=float)
            
            if not weight or price_color is None or price_mono is None:
                flash('Todos os campos são obrigatórios', 'error')
                return render_template('admin_weight_form.html', paper=paper)
            
            # Verificar se já existe essa gramatura para este papel
            existing = PaperWeight.query.filter_by(paper_type_id=paper_id, weight=weight).first()
            if existing:
                flash('Já existe essa gramatura para este tipo de papel', 'error')
                return render_template('admin_weight_form.html', paper=paper)
            
            # Criar nova gramatura
            paper_weight = PaperWeight(
                paper_type_id=paper_id,
                weight=weight,
                price_color=price_color,
                price_mono=price_mono
            )
            db.session.add(paper_weight)
            db.session.commit()
            
            flash('Gramatura adicionada com sucesso!', 'success')
            return redirect(url_for('admin_paper_weights', paper_id=paper_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao adicionar gramatura: {str(e)}', 'error')
    
    return render_template('admin_weight_form.html', paper=paper)

# ============================================
# CRUD ADMINISTRATIVO - TIPOS DE ENCADERNAÇÃO
# ============================================

@app.route('/admin/bindings')
@admin_required
def admin_bindings():
    bindings = BindingType.query.all()
    return render_template('admin_bindings.html', bindings=bindings)

@app.route('/admin/bindings/create', methods=['GET', 'POST'])
@admin_required
def admin_bindings_create():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            display_name = request.form.get('display_name', '').strip()
            description = request.form.get('description', '').strip()
            price = request.form.get('price', type=float)
            
            if not name or not display_name or price is None:
                flash('Nome, nome de exibição e preço são obrigatórios', 'error')
                return render_template('admin_binding_form.html')
            
            # Verificar se já existe
            existing = BindingType.query.filter_by(name=name).first()
            if existing:
                flash('Já existe um tipo de encadernação com esse nome', 'error')
                return render_template('admin_binding_form.html')
            
            # Criar novo tipo de encadernação
            binding_type = BindingType(
                name=name,
                display_name=display_name,
                description=description,
                price=price
            )
            db.session.add(binding_type)
            db.session.commit()
            
            flash('Tipo de encadernação criado com sucesso!', 'success')
            return redirect(url_for('admin_bindings'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar tipo de encadernação: {str(e)}', 'error')
    
    return render_template('admin_binding_form.html')

# ============================================
# CRUD ADMINISTRATIVO - TIPOS DE ACABAMENTO
# ============================================

@app.route('/admin/finishings')
@admin_required
def admin_finishings():
    finishings = FinishingType.query.all()
    return render_template('admin_finishings.html', finishings=finishings)

@app.route('/admin/finishings/create', methods=['GET', 'POST'])
@admin_required
def admin_finishings_create():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            display_name = request.form.get('display_name', '').strip()
            description = request.form.get('description', '').strip()
            price = request.form.get('price', type=float)
            
            if not name or not display_name or price is None:
                flash('Nome, nome de exibição e preço são obrigatórios', 'error')
                return render_template('admin_finishing_form.html')
            
            # Verificar se já existe
            existing = FinishingType.query.filter_by(name=name).first()
            if existing:
                flash('Já existe um tipo de acabamento com esse nome', 'error')
                return render_template('admin_finishing_form.html')
            
            # Criar novo tipo de acabamento
            finishing_type = FinishingType(
                name=name,
                display_name=display_name,
                description=description,
                price=price
            )
            db.session.add(finishing_type)
            db.session.commit()
            
            flash('Tipo de acabamento criado com sucesso!', 'success')
            return redirect(url_for('admin_finishings'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar tipo de acabamento: {str(e)}', 'error')
    
    return render_template('admin_finishing_form.html')

# ============================================
# API ENDPOINTS PARA INTEGRAÇÃO EXTERNA (WOOCOMMERCE)
# ============================================

from datetime import datetime

def validate_api_request(request):
    """Validar requisição API com key segura obrigatória"""
    # Verificar API key (obrigatória via environment)
    api_key = request.headers.get('X-API-Key')
    expected_key = os.environ.get('API_KEY')
    
    if not expected_key:
        return False, 'API não configurada corretamente - contate o administrador'
    
    if not api_key:
        return False, 'Cabeçalho X-API-Key é obrigatório'
    
    if api_key != expected_key:
        return False, 'API key inválida'
    
    return True, None

def get_cors_origin(request):
    """Determinar origem CORS permitida com validação rigorosa"""
    origin = request.headers.get('Origin', '')
    
    # Lista exata de origens permitidas para WooCommerce
    allowed_origins = [
        'http://localhost:3000',
        'https://localhost:3000',
        'http://localhost:8080',
        'https://localhost:8080'
    ]
    
    # Permitir subdomínios específicos do WooCommerce/WordPress
    allowed_domains = [
        '.woocommerce.com',
        '.wordpress.com',
        '.woocommerce.org',
        '.wordpress.org'
    ]
    
    if not origin:
        # Para testes locais sem Origin header
        return '*'
    
    # Verificar origem exata
    if origin in allowed_origins:
        return origin
    
    # Verificar subdomínios permitidos
    for domain in allowed_domains:
        if origin.endswith(domain) and ('://' in origin):
            # Validar que é HTTPS para domínios remotos
            if origin.startswith('https://'):
                return origin
    
    return None

@app.route('/api/v1/calculate_final', methods=['POST', 'OPTIONS'])
def api_calculate_final():
    """
    Endpoint dedicado para WooCommerce calcular custo final avançado
    
    POST /api/v1/calculate_final
    Content-Type: application/json
    
    Request JSON:
    {
        "color_pages": 5,
        "mono_pages": 10,
        "paper_type": "sulfite",
        "paper_weight": 90,
        "binding_type": "spiral", 
        "finishing": "laminacao,verniz",
        "copy_quantity": 2
    }
    
    Response JSON:
    {
        "success": true,
        "cost_details": {
            "pages_cost": 1.50,
            "binding_cost": 5.00,
            "finishing_cost": 5.50,
            "cost_per_copy": 12.00,
            "total_cost": 24.00,
            "copy_quantity": 2
        },
        "breakdown": {
            "paper_info": "Sulfite 90g",
            "binding_info": "Espiral plástica",
            "finishing_info": "Laminação, Verniz"
        },
        "timestamp": "2024-09-26T15:30:00Z"
    }
    """
    
    # Handle CORS preflight requests
    if request.method == 'OPTIONS':
        cors_origin = get_cors_origin(request)
        if not cors_origin:
            return jsonify({'error': 'Origem não permitida'}), 403
            
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', cors_origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
        response.headers.add('Access-Control-Allow-Methods', 'POST,OPTIONS')
        if cors_origin != '*':
            response.headers.add('Vary', 'Origin')
        return response
    
    try:
        # Validar API key e origem
        is_valid, error_msg = validate_api_request(request)
        cors_origin = get_cors_origin(request)
        
        if not is_valid:
            response = jsonify({
                'success': False,
                'error': error_msg,
                'error_code': 'UNAUTHORIZED'
            })
            if cors_origin:
                response.headers.add('Access-Control-Allow-Origin', cors_origin)
            return response, 401
        
        if not cors_origin:
            return jsonify({
                'success': False,
                'error': 'Origem não permitida',
                'error_code': 'FORBIDDEN_ORIGIN'
            }), 403
        
        # Log da requisição para debugging (sem dados sensíveis)
        print(f"[API] WooCommerce request at {datetime.now()}")
        print(f"[API] Content-Type: {request.content_type}")
        print(f"[API] Method: {request.method}")
        print(f"[API] Origin: {request.headers.get('Origin', 'N/A')}")
        
        # Verificar Content-Type
        if not request.is_json:
            response = jsonify({
                'success': False,
                'error': 'Content-Type deve ser application/json',
                'error_code': 'INVALID_CONTENT_TYPE'
            })
            response.headers.add('Access-Control-Allow-Origin', cors_origin or '*')
            return response, 400
        
        # Obter dados JSON
        data = request.get_json()
        
        if not data:
            response = jsonify({
                'success': False,
                'error': 'Corpo da requisição JSON é obrigatório',
                'error_code': 'MISSING_JSON_BODY'
            })
            response.headers.add('Access-Control-Allow-Origin', cors_origin or '*')
            return response, 400
        
        # Validação de campos obrigatórios
        required_fields = ['color_pages', 'mono_pages']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            response = jsonify({
                'success': False,
                'error': f'Campos obrigatórios ausentes: {", ".join(missing_fields)}',
                'error_code': 'MISSING_REQUIRED_FIELDS',
                'missing_fields': missing_fields
            })
            response.headers.add('Access-Control-Allow-Origin', cors_origin or '*')
            return response, 400
        
        # Extrair e validar parâmetros
        try:
            color_pages = int(data.get('color_pages', 0))
            mono_pages = int(data.get('mono_pages', 0))
            paper_type = str(data.get('paper_type', 'sulfite')).strip().lower()
            paper_weight = int(data.get('paper_weight', 90))
            binding_type = str(data.get('binding_type', 'grampo')).strip().lower()
            finishing = str(data.get('finishing', '')).strip().lower() if data.get('finishing') else ''
            copy_quantity = int(data.get('copy_quantity', 1))
            
        except (ValueError, TypeError):
            response = jsonify({
                'success': False,
                'error': 'Tipos de dados inválidos. Verifique os valores numéricos.',
                'error_code': 'INVALID_DATA_TYPES'
            })
            response.headers.add('Access-Control-Allow-Origin', cors_origin or '*')
            return response, 400
        
        # Validação de valores
        if color_pages < 0 or mono_pages < 0:
            return jsonify({
                'success': False,
                'error': 'Número de páginas não pode ser negativo',
                'error_code': 'INVALID_PAGE_COUNT'
            }), 400
        
        if color_pages + mono_pages == 0:
            return jsonify({
                'success': False,
                'error': 'Total de páginas deve ser maior que zero',
                'error_code': 'ZERO_PAGES'
            }), 400
        
        if copy_quantity <= 0:
            return jsonify({
                'success': False,
                'error': 'Quantidade de cópias deve ser maior que zero',
                'error_code': 'INVALID_QUANTITY'
            }), 400
        
        if copy_quantity > 1000:
            return jsonify({
                'success': False,
                'error': 'Quantidade máxima de cópias é 1000',
                'error_code': 'QUANTITY_EXCEEDED'
            }), 400
        
        # Validar limites superiores rigorosos
        if color_pages + mono_pages > 500:
            response = jsonify({
                'success': False,
                'error': 'Total de páginas excede o limite máximo de 500',
                'error_code': 'PAGE_LIMIT_EXCEEDED'
            })
            response.headers.add('Access-Control-Allow-Origin', cors_origin or '*')
            return response, 400
        
        # Validar peso do papel nos valores permitidos
        valid_weights = [75, 90, 115, 120, 150]
        if paper_weight not in valid_weights:
            paper_weight = 90  # Default seguro
        
        # Validar tipos de papel rigorosamente
        valid_paper_types = ['sulfite', 'couche', 'reciclado']
        if paper_type not in valid_paper_types:
            response = jsonify({
                'success': False,
                'error': f'Tipo de papel inválido. Valores permitidos: {", ".join(valid_paper_types)}',
                'error_code': 'INVALID_PAPER_TYPE'
            })
            response.headers.add('Access-Control-Allow-Origin', cors_origin or '*')
            return response, 400
        
        # Validar tipos de encadernação rigorosamente
        valid_binding_types = ['grampo', 'spiral', 'wire-o', 'capa-dura']
        if binding_type not in valid_binding_types:
            response = jsonify({
                'success': False,
                'error': f'Tipo de encadernação inválido. Valores permitidos: {", ".join(valid_binding_types)}',
                'error_code': 'INVALID_BINDING_TYPE'
            })
            response.headers.add('Access-Control-Allow-Origin', cors_origin or '*')
            return response, 400
        
        # Limpar e validar acabamentos
        if finishing:
            finishing = finishing.strip()
            if finishing:
                valid_finishings = ['laminacao', 'verniz', 'dobra', 'perfuracao']
                finishing_list = [f.strip() for f in finishing.split(',')]
                finishing_list = [f for f in finishing_list if f in valid_finishings]
                finishing = ','.join(finishing_list) if finishing_list else None
            else:
                finishing = None
        
        # Calcular custo usando função existente
        cost_details = calculate_advanced_cost(
            color_pages=color_pages,
            mono_pages=mono_pages,
            paper_type=paper_type,
            paper_weight=paper_weight,
            binding_type=binding_type,
            finishing=finishing,
            copy_quantity=copy_quantity
        )
        
        # Preparar informações descritivas
        paper_info = f"{paper_type.title()} {paper_weight}g"
        
        binding_names = {
            'grampo': 'Grampo (2 grampos)',
            'spiral': 'Espiral plástica',
            'wire-o': 'Wire-o (espiral metálica)',
            'capa-dura': 'Capa dura'
        }
        binding_info = binding_names.get(binding_type, binding_type.title())
        
        finishing_info = ''
        if finishing:
            finishing_names = {
                'laminacao': 'Laminação',
                'verniz': 'Verniz',
                'dobra': 'Dobra',
                'perfuracao': 'Perfuração'
            }
            finishing_list = [finishing_names.get(f.strip(), f.strip().title()) 
                            for f in finishing.split(',')]
            finishing_info = ', '.join(finishing_list)
        
        # Resposta estruturada para WooCommerce
        response_data = {
            'success': True,
            'cost_details': cost_details,
            'breakdown': {
                'paper_info': paper_info,
                'binding_info': binding_info,
                'finishing_info': finishing_info,
                'total_pages': color_pages + mono_pages,
                'color_pages': color_pages,
                'mono_pages': mono_pages
            },
            'request_summary': {
                'paper_type': paper_type,
                'paper_weight': paper_weight,
                'binding_type': binding_type,
                'finishing': finishing,
                'copy_quantity': copy_quantity
            },
            'timestamp': datetime.now().isoformat()
        }
        
        # Log da resposta para debugging
        print(f"[API] Successful calculation: R$ {cost_details['total_cost']}")
        
        # Configurar resposta com CORS
        response = jsonify(response_data)
        response.headers.add('Access-Control-Allow-Origin', cors_origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
        response.headers.add('Access-Control-Allow-Methods', 'POST,OPTIONS')
        response.headers.add('Content-Type', 'application/json; charset=utf-8')
        if cors_origin != '*':
            response.headers.add('Vary', 'Origin')
        
        return response
        
    except Exception as e:
        # Log detalhado do erro
        print(f"[API] Error in calculate_final: {str(e)}")
        print(f"[API] Error type: {type(e).__name__}")
        
        # Configurar resposta de erro com CORS
        cors_origin = get_cors_origin(request) or '*'
        response = jsonify({
            'success': False,
            'error': 'Erro interno do servidor ao calcular custos',
            'error_code': 'INTERNAL_ERROR',
            'timestamp': datetime.now().isoformat()
        })
        response.headers.add('Access-Control-Allow-Origin', cors_origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
        response.headers.add('Access-Control-Allow-Methods', 'POST,OPTIONS')
        if cors_origin != '*':
            response.headers.add('Vary', 'Origin')
        return response, 500

@app.route('/api/v1/health', methods=['GET'])
def api_health():
    """Endpoint de verificação de saúde da API"""
    try:
        # Verificar conexão com banco de dados
        from sqlalchemy import text
        db.session.execute(text('SELECT 1'))
        
        return jsonify({
            'status': 'healthy',
            'service': 'web2print-api',
            'version': '1.0',
            'timestamp': datetime.now().isoformat(),
            'database': 'connected'
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'service': 'web2print-api',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

# ============================================
# ROTAS PRINCIPAIS DO SISTEMA (EXISTENTES)
# ============================================

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
            
            # Obter acabamentos selecionados (múltiplos checkboxes)
            finishing_list = request.form.getlist('finishing')
            finishing = ','.join(finishing_list) if finishing_list else None
            
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
    
    # Verificar se o pedido foi configurado
    if user.order_configured:
        # Calcular páginas baseado no tipo de impressão escolhido
        if user.print_type == 'color':
            # Tudo em cores
            color_pages_final = user.color_pages + user.mono_pages
            mono_pages_final = 0
        elif user.print_type == 'mono':
            # Tudo em P&B
            color_pages_final = 0
            mono_pages_final = user.color_pages + user.mono_pages
        else:  # mixed
            # Manter separação original
            color_pages_final = user.color_pages or 0
            mono_pages_final = user.mono_pages or 0
        
        # Recalcular custo detalhado para exibição
        cost_details = calculate_advanced_cost(
            color_pages_final, mono_pages_final,
            user.paper_type or 'sulfite', user.paper_weight or 90,
            user.binding_type or 'grampo', user.finishing,
            user.copy_quantity or 1
        )
        
        cart_data = {
            'user': user,
            'configured': True,
            'cost_details': cost_details
        }
    else:
        # Mostrar dados básicos e link para configuração
        cart_data = {
            'user': user,
            'configured': False,
            'basic_cost': user.estimated_cost or 0.0
        }
    
    return render_template('cart.html', **cart_data)

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run(host='0.0.0.0', port=5000, debug=True)
