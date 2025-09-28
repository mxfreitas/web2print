from flask import Flask, request, render_template, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
import PyPDF2
import pymupdf as fitz  # PyMuPDF para análise de PDFs
import os
import requests
import uuid
import hashlib
import tempfile
import contextlib
import logging
import time
import json
import threading
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ============================================
# CONFIGURAÇÕES DE OTIMIZAÇÃO - FASE 1
# ============================================

# Configurações específicas para ambiente Replit e performance
MAX_PDF_SIZE_SYNC = int(os.getenv('MAX_SYNC_PDF_SIZE', '10485760'))  # 10MB default
MAX_PDF_SIZE_TOTAL = int(os.getenv('MAX_PDF_SIZE_TOTAL', '52428800'))  # 50MB total
HEALTH_CHECK_TIMEOUT = int(os.getenv('HEALTH_CHECK_TIMEOUT', '3'))  # 3 segundos
PDF_DOWNLOAD_TIMEOUT = int(os.getenv('PDF_DOWNLOAD_TIMEOUT', '30'))  # 30 segundos
CLEANUP_LOG_LEVEL = os.getenv('CLEANUP_LOG_LEVEL', 'INFO').upper()
ENABLE_SIZE_PRECHECK = os.getenv('ENABLE_SIZE_PRECHECK', 'true').lower() == 'true'

# Configurar logging estruturado
logging.basicConfig(
    level=getattr(logging, CLEANUP_LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('web2print')

# ============================================
# CONTEXT MANAGER PARA ARQUIVOS TEMPORÁRIOS
# ============================================

@contextlib.contextmanager
def secure_temp_pdf_file(suffix='.pdf', prefix='web2print_'):
    """
    Context manager robusto para arquivos PDF temporários com cleanup garantido.
    
    Features:
    - Cleanup automático garantido via context manager
    - Logging detalhado de operações
    - Tratamento de erro robusto
    - Geração de nomes únicos com timestamp
    """
    temp_path = None
    start_time = time.time()
    
    try:
        # Criar arquivo temporário com nome único
        timestamp = int(time.time() * 1000)  # milliseconds
        with tempfile.NamedTemporaryFile(
            suffix=suffix, 
            prefix=f"{prefix}{timestamp}_", 
            delete=False
        ) as temp_file:
            temp_path = temp_file.name
            
        logger.info(f"Arquivo temporário criado: {temp_path}")
        yield temp_path
        
    except Exception as e:
        logger.error(f"Erro durante uso do arquivo temporário {temp_path}: {e}")
        raise
        
    finally:
        # CRÍTICO: Cleanup garantido independente de sucesso/erro
        cleanup_duration = time.time() - start_time
        
        if temp_path and os.path.exists(temp_path):
            try:
                file_size = os.path.getsize(temp_path)
                os.remove(temp_path)
                logger.info(
                    f"Arquivo temporário removido com sucesso: {temp_path} "
                    f"(tamanho: {file_size:,} bytes, duração: {cleanup_duration:.2f}s)"
                )
            except OSError as cleanup_error:
                logger.error(
                    f"FALHA CRÍTICA: Não foi possível remover arquivo temporário {temp_path}: {cleanup_error}"
                )
                # Em produção: alertar admin ou adicionar a lista de cleanup
                # TODO: Implementar sistema de cleanup de emergência
        elif temp_path:
            logger.warning(f"Arquivo temporário não encontrado para cleanup: {temp_path}")
        else:
            logger.debug("Nenhum arquivo temporário para cleanup")

# ============================================
# FUNÇÕES DE VERIFICAÇÃO DE TAMANHO
# ============================================

def check_pdf_size_before_download(url, max_size=None):
    """
    Verifica o tamanho do PDF antes do download para otimizar performance.
    
    Args:
        url: URL do PDF para verificar
        max_size: Tamanho máximo permitido em bytes
        
    Returns:
        dict: {'allowed': bool, 'size': int, 'message': str}
    """
    if not ENABLE_SIZE_PRECHECK:
        return {'allowed': True, 'size': 0, 'message': 'Pré-verificação desabilitada'}
        
    max_size = max_size or MAX_PDF_SIZE_TOTAL
    
    try:
        logger.info(f"Verificando tamanho do PDF: {url}")
        head_response = requests.head(url, timeout=5, allow_redirects=True)
        head_response.raise_for_status()
        
        content_length = head_response.headers.get('content-length')
        if not content_length:
            logger.warning(f"Content-Length não disponível para {url}")
            return {'allowed': True, 'size': 0, 'message': 'Tamanho não determinável'}
            
        file_size = int(content_length)
        
        if file_size > max_size:
            logger.warning(f"Arquivo muito grande: {file_size:,} bytes (máx: {max_size:,})")
            return {
                'allowed': False, 
                'size': file_size,
                'message': f'Arquivo muito grande: {file_size/1024/1024:.1f}MB (máx: {max_size/1024/1024:.1f}MB)'
            }
            
        logger.info(f"Tamanho do arquivo OK: {file_size:,} bytes")
        return {'allowed': True, 'size': file_size, 'message': 'Tamanho aprovado'}
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao verificar tamanho do PDF {url}: {e}")
        # Em caso de erro, permitir download (pode ser problema temporário)
        return {'allowed': True, 'size': 0, 'message': f'Erro na verificação: {e}'}

def get_processing_strategy(file_size):
    """
    Determina a estratégia de processamento baseada no tamanho do arquivo.
    
    Args:
        file_size: Tamanho do arquivo em bytes
        
    Returns:
        dict: {'strategy': str, 'timeout': int, 'message': str}
    """
    if file_size <= MAX_PDF_SIZE_SYNC:
        return {
            'strategy': 'sync',
            'timeout': 15,
            'message': 'Processamento rápido síncrono'
        }
    else:
        return {
            'strategy': 'sync_slow',
            'timeout': 45,
            'message': 'Processamento síncrono estendido (arquivo grande)'
        }

# ============================================
# FUNÇÕES DE MONITORING MELHORADAS
# ============================================

def log_api_performance(operation, duration, file_size=None, success=True):
    """
    Log estruturado de performance para monitoramento.
    """
    log_data = {
        'operation': operation,
        'duration_seconds': round(duration, 3),
        'success': success,
        'timestamp': datetime.now().isoformat()
    }
    
    if file_size:
        log_data['file_size_bytes'] = file_size
        log_data['processing_rate_mb_per_sec'] = round((file_size / 1024 / 1024) / duration, 2)
    
    if success:
        logger.info(f"Performance: {log_data}")
    else:
        logger.warning(f"Performance (failed): {log_data}")

# SEGURANÇA: Configuração de chave secreta e sessões
secret_key = os.getenv('SECRET_KEY', 'web2print-secret-key-2024-replit-env')
is_production = os.getenv('FLASK_ENV') == 'production' or os.getenv('ENV') == 'production'

# CRÍTICO: Não permitir chave padrão em produção
if is_production and secret_key == 'web2print-secret-key-2024-replit-env':
    raise RuntimeError("ERRO DE SEGURANÇA: SECRET_KEY deve ser definida em produção! Configure a variável de ambiente SECRET_KEY com uma chave secreta forte.")

app.secret_key = secret_key

# Configurações de sessão seguras
app.config['SESSION_COOKIE_SECURE'] = os.getenv('HTTPS_ENABLED', 'False').lower() == 'true'  # True em produção com HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'  # Mais restritivo para admin
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutos

db = SQLAlchemy(app)
csrf = CSRFProtect(app)  # Proteção CSRF
app.app_context().push()

# Log de inicialização com configurações
logger.info(f"Web2Print iniciado com configurações:")
logger.info(f"  - MAX_PDF_SIZE_SYNC: {MAX_PDF_SIZE_SYNC/1024/1024:.1f}MB")
logger.info(f"  - MAX_PDF_SIZE_TOTAL: {MAX_PDF_SIZE_TOTAL/1024/1024:.1f}MB")
logger.info(f"  - HEALTH_CHECK_TIMEOUT: {HEALTH_CHECK_TIMEOUT}s")
logger.info(f"  - ENABLE_SIZE_PRECHECK: {ENABLE_SIZE_PRECHECK}")
logger.info(f"  - Ambiente: {'Produção' if is_production else 'Desenvolvimento'}")
logger.info(f"  - Log Level: {CLEANUP_LOG_LEVEL}")

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

# MODELO PARA SISTEMA ASSÍNCRONO - PRIORIDADE 1
class Job(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # UUID como string
    job_type = db.Column(db.String(50), nullable=False)  # 'pdf_analysis_url'
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending, running, completed, failed
    progress = db.Column(db.Integer, nullable=False, default=0)  # 0-100
    input_data = db.Column(db.Text, nullable=False)  # JSON com dados de entrada
    result_data = db.Column(db.Text, nullable=True)  # JSON com resultado
    error_message = db.Column(db.String(500), nullable=True)  # mensagem de erro
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    expires_at = db.Column(db.DateTime, nullable=False)  # quando o job expira
    started_at = db.Column(db.DateTime, nullable=True)  # quando começou processamento
    completed_at = db.Column(db.DateTime, nullable=True)  # quando terminou
    
    # Índices para consultas eficientes
    __table_args__ = (
        db.Index('idx_job_status_created', 'status', 'created_at'),
        db.Index('idx_job_expires', 'expires_at'),
    )

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
        
        # SEGURANÇA: Não criar admin padrão - deve ser criado manualmente
        # Para criar admin, execute: flask create-admin
        print("⚠️  Para criar um usuário admin, execute: flask create-admin")
        
        db.session.commit()
        print("✅ Dados iniciais inseridos no banco de dados!")
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erro ao inserir dados iniciais: {str(e)}")

# ============================================
# COMANDO CLI PARA CRIAR ADMIN SEGURO
# ============================================

@app.cli.command()
def create_admin():
    """Criar usuário administrador com senha segura"""
    import getpass
    
    print("🔐 Criação de Usuário Administrador")
    print("=" * 40)
    
    username = input("Digite o nome de usuário: ").strip()
    if not username:
        print("❌ Nome de usuário é obrigatório!")
        return
    
    # Verificar se admin já existe
    existing_admin = Admin.query.filter_by(username=username).first()
    if existing_admin:
        print(f"❌ Admin '{username}' já existe!")
        return
    
    # Solicitar senha de forma segura (oculta)
    password = getpass.getpass("Digite a senha: ")
    password_confirm = getpass.getpass("Confirme a senha: ")
    
    if password != password_confirm:
        print("❌ Senhas não coincidem!")
        return
    
    if len(password) < 8:
        print("❌ Senha deve ter pelo menos 8 caracteres!")
        return
    
    try:
        # Criar hash seguro da senha
        password_hash = generate_password_hash(password)
        
        # Criar admin
        admin = Admin(
            username=username,
            password_hash=password_hash,
            active=True
        )
        
        db.session.add(admin)
        db.session.commit()
        
        print(f"✅ Admin '{username}' criado com sucesso!")
        print("🔒 Senha foi criptografada com Werkzeug password hashing")
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erro ao criar admin: {str(e)}")

@app.cli.command()
def reset_admin_password():
    """Resetar senha de um administrador"""
    import getpass
    
    print("🔄 Reset de Senha de Administrador")
    print("=" * 40)
    
    username = input("Digite o nome de usuário: ").strip()
    if not username:
        print("❌ Nome de usuário é obrigatório!")
        return
    
    admin = Admin.query.filter_by(username=username).first()
    if not admin:
        print(f"❌ Admin '{username}' não encontrado!")
        return
    
    password = getpass.getpass("Digite a nova senha: ")
    password_confirm = getpass.getpass("Confirme a nova senha: ")
    
    if password != password_confirm:
        print("❌ Senhas não coincidem!")
        return
    
    if len(password) < 8:
        print("❌ Senha deve ter pelo menos 8 caracteres!")
        return
    
    try:
        # Atualizar hash da senha
        admin.password_hash = generate_password_hash(password)
        db.session.commit()
        
        print(f"✅ Senha do admin '{username}' foi resetada com sucesso!")
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erro ao resetar senha: {str(e)}")

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
        
        # Buscar admin pelo username
        admin = Admin.query.filter_by(username=username, active=True).first()
        
        # SEGURANÇA: Usar Werkzeug password hashing
        if admin and check_password_hash(admin.password_hash, password):
            session['admin_logged_in'] = True
            session['admin_username'] = username
            session.permanent = True  # Usar tempo de sessão configurado
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

@app.route('/api/v1/analyze_pdf_url', methods=['POST', 'OPTIONS'])
@csrf.exempt
def api_analyze_pdf_url():
    """
    Endpoint para análise de PDF via URL - WordPress Plugin Integration
    Baixa PDF temporariamente e analisa com PyMuPDF para precisão máxima
    
    POST /api/v1/analyze_pdf_url
    Content-Type: application/json
    {
        "pdf_url": "https://exemplo.com/uploads/arquivo.pdf"
    }
    """
    # CORS headers para WordPress
    if request.method == 'OPTIONS':
        return '', 200, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, X-API-Key',
        }
    
    try:
        # CRÍTICO: Verificar autenticação via API Key
        api_key = request.headers.get('X-API-Key') 
        expected_key = os.getenv('WEB2PRINT_API_KEY')
        
        # SEGURANÇA: Não permitir chave padrão em produção
        if not expected_key:
            if is_production:
                return jsonify({
                    'success': False,
                    'error': 'WEB2PRINT_API_KEY deve ser configurada em produção',
                    'error_code': 'PRODUCTION_KEY_REQUIRED'
                }), 500
            expected_key = 'web2print-dev-key-only'
        
        if not api_key or api_key != expected_key:
            return jsonify({
                'success': False,
                'error': 'API Key inválida ou ausente',
                'error_code': 'UNAUTHORIZED'
            }), 401
        
        # Parsing JSON
        data = request.get_json()
        if not data or 'pdf_url' not in data:
            return jsonify({
                'success': False,
                'error': 'URL do PDF é obrigatória',
                'error_code': 'MISSING_URL'
            }), 400
        
        pdf_url = data['pdf_url']
        
        # SEGURANÇA: Validação robusta de URL para prevenir SSRF
        from urllib.parse import urlparse
        import ipaddress
        
        parsed = urlparse(pdf_url)
        if parsed.scheme not in ('http', 'https'):
            return jsonify({
                'success': False,
                'error': 'URL inválida - deve usar http:// ou https://',
                'error_code': 'INVALID_URL_SCHEME'
            }), 400
        
        # SEGURANÇA ROBUSTA: Verificar TODAS as IPs (IPv4 e IPv6) 
        try:
            import socket
            hostname = parsed.hostname or ''
            
            # Resolver todos os IPs (A e AAAA records)
            try:
                addr_info = socket.getaddrinfo(hostname, None)
            except socket.gaierror:
                return jsonify({
                    'success': False,
                    'error': 'Não foi possível resolver hostname',
                    'error_code': 'DNS_RESOLUTION_FAILED'
                }), 400
            
            for family, type, proto, canonname, sockaddr in addr_info:
                ip = sockaddr[0]  # IP está sempre no primeiro elemento
                try:
                    ip_obj = ipaddress.ip_address(ip)
                    
                    # Bloquear IPs privados/locais/reservados (IPv4 e IPv6)
                    if (ip_obj.is_private or ip_obj.is_loopback or 
                        ip_obj.is_link_local or ip_obj.is_reserved or
                        ip_obj.is_multicast):
                        return jsonify({
                            'success': False,
                            'error': f'IP {ip} é interno/privado - bloqueado por segurança',
                            'error_code': 'SSRF_BLOCKED'
                        }), 403
                        
                except ValueError:
                    # IP inválido
                    return jsonify({
                        'success': False,
                        'error': f'IP inválido detectado: {ip}',
                        'error_code': 'INVALID_IP'
                    }), 400
                    
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Erro na validação de segurança: {str(e)}',
                'error_code': 'SECURITY_CHECK_FAILED'
            }), 400
        
        # Validação adicional: deve ter extensão .pdf
        if not pdf_url.lower().endswith('.pdf'):
            return jsonify({
                'success': False,
                'error': 'URL deve apontar para arquivo .pdf',
                'error_code': 'INVALID_FILE_TYPE'
            }), 400
        
        # Baixar PDF temporariamente via requests
        try:
            logger.info(f"Iniciando download seguro de PDF: {pdf_url}")
            
            # FASE 1: DOWNLOAD SEGURO COM TIMEOUT OTIMIZADO
            # Usar timeout duplo: (connect_timeout, read_timeout) para maior controle
            connect_timeout = 5  # Conectar rápido
            read_timeout = PDF_DOWNLOAD_TIMEOUT  # Leitura baseada na configuração
            
            # SEGURANÇA: Bloquear redirects para prevenir SSRF via redirect  
            response = requests.get(
                pdf_url, 
                timeout=(connect_timeout, read_timeout), 
                stream=True, 
                allow_redirects=False,
                headers={'User-Agent': 'Web2Print-Downloader/1.0'}
            )
            
            # Verificar se é redirect
            if response.status_code in (301, 302, 303, 307, 308):
                return jsonify({
                    'success': False,
                    'error': 'Redirects não são permitidos por segurança',
                    'error_code': 'REDIRECT_BLOCKED'
                }), 403
                
            response.raise_for_status()
            
            # CRÍTICO: Limite de tamanho para prevenir ataques
            max_size = 50 * 1024 * 1024  # 50MB máximo
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > max_size:
                return jsonify({
                    'success': False,
                    'error': 'Arquivo muito grande. Máximo 50MB.',
                    'error_code': 'FILE_TOO_LARGE'
                }), 400
            
            # CRÍTICO: Verificar Content-Type rigorosamente
            content_type = response.headers.get('content-type', '')
            if not content_type.startswith('application/pdf'):
                return jsonify({
                    'success': False,
                    'error': f'Content-Type inválido: {content_type}. Apenas application/pdf é aceito.',
                    'error_code': 'INVALID_CONTENT_TYPE'
                }), 400
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Falha na requisição HTTP para PDF: {str(e)}")
            return jsonify({
                'success': False,
                'error': f'Erro ao conectar ou iniciar download: {str(e)}',
                'error_code': 'HTTP_REQUEST_FAILED'
            }), 422
        
        # FASE 1: VERIFICAÇÃO OTIMIZADA DE TAMANHO
        operation_start = time.time()
        
        # Verificar tamanho antes do download (otimização)
        size_check = check_pdf_size_before_download(pdf_url, MAX_PDF_SIZE_TOTAL)
        if not size_check['allowed']:
            logger.warning(f"Download bloqueado por tamanho: {size_check['message']}")
            return jsonify({
                'success': False,
                'error': size_check['message'],
                'error_code': 'FILE_TOO_LARGE_PRECHECK'
            }), 400
            
        # PRIORIDADE 1: DECISÃO SÍNCRONO vs ASSÍNCRONO  
        file_size = size_check['size'] if size_check['size'] > 0 else 0
        
        # Se arquivo grande (>10MB) ou tamanho desconhecido (potencialmente grande), usar processamento assíncrono
        if file_size > MAX_PDF_SIZE_SYNC or file_size == 0:
            logger.info(f"Arquivo grande ou tamanho desconhecido ({file_size:,} bytes) - criando job assíncrono")
            
            # Criar job assíncrono
            job_id = str(uuid.uuid4())
            input_data = {
                'pdf_url': pdf_url,
                'file_size_hint': file_size,
                'api_key': api_key  # Para o worker usar
            }
            
            job = Job(
                id=job_id,
                job_type='pdf_analysis_url',
                status='pending',
                progress=0,
                input_data=json.dumps(input_data),
                expires_at=datetime.now() + timedelta(hours=2)  # Expira em 2 horas
            )
            
            db.session.add(job)
            db.session.commit()
            
            logger.info(f"Job criado: {job_id} para PDF: {pdf_url}")
            
            # Retornar 202 Accepted com job_id para polling
            return jsonify({
                'success': True,
                'job_id': job_id,
                'status': 'processing',
                'message': 'PDF enfileirado para processamento assíncrono',
                'estimated_time_seconds': 45 if file_size > 0 else 60,
                'polling_url': f'/api/v1/jobs/{job_id}'
            }), 202
        
        else:
            logger.info(f"Arquivo pequeno ({file_size:,} bytes) - processamento síncrono")
        
        # PROCESSAMENTO SÍNCRONO PARA ARQUIVOS PEQUENOS
        with secure_temp_pdf_file() as temp_path:
            # DOWNLOAD SEGURO COM LIMITE RÍGIDO DE BYTES
            downloaded = 0
            chunk_count = 0
            download_start = time.time()
            
            # Obter Content-Length se disponível para melhor logging
            expected_size = response.headers.get('content-length')
            if expected_size:
                expected_size = int(expected_size)
                logger.info(f"Tamanho esperado: {expected_size:,} bytes ({expected_size/1024/1024:.1f}MB)")
            else:
                logger.warning("Content-Length não disponível - aplicando limite cumulativo rígido")
                expected_size = None
            
            with open(temp_path, 'wb') as temp_file:
                try:
                    for chunk in response.iter_content(chunk_size=64*1024):  # 64KB chunks
                        if chunk:
                            chunk_count += 1
                            downloaded += len(chunk)
                            
                            # LIMITE RÍGIDO: Parar imediatamente se exceder limite
                            if downloaded > MAX_PDF_SIZE_TOTAL:
                                elapsed = time.time() - download_start
                                logger.error(
                                    f"Download abortado por exceder limite: {downloaded:,} bytes "
                                    f"(máx: {MAX_PDF_SIZE_TOTAL:,}) em {elapsed:.2f}s, {chunk_count} chunks"
                                )
                                return jsonify({
                                    'success': False,
                                    'error': f'Arquivo muito grande para download: {downloaded/1024/1024:.1f}MB (máximo permitido: {MAX_PDF_SIZE_TOTAL/1024/1024:.1f}MB)',
                                    'error_code': 'PAYLOAD_TOO_LARGE',
                                    'downloaded_bytes': downloaded,
                                    'max_bytes': MAX_PDF_SIZE_TOTAL
                                }), 413  # Payload Too Large
                            
                            temp_file.write(chunk)
                            
                            # Log de progresso para arquivos grandes (a cada 10MB)
                            if downloaded % (10 * 1024 * 1024) == 0 or (downloaded > 0 and chunk_count % 100 == 0):
                                elapsed = time.time() - download_start
                                speed_mbps = (downloaded / (1024 * 1024)) / max(elapsed, 0.1)
                                logger.debug(f"Download em progresso: {downloaded/1024/1024:.1f}MB ({speed_mbps:.1f}MB/s)")
                                
                except requests.exceptions.RequestException as download_error:
                    elapsed = time.time() - download_start
                    logger.error(
                        f"Erro durante download: {download_error} - "
                        f"Baixados: {downloaded:,} bytes em {elapsed:.2f}s"
                    )
                    return jsonify({
                        'success': False,
                        'error': 'Falha durante download do arquivo PDF',
                        'error_code': 'DOWNLOAD_FAILED',
                        'details': str(download_error)
                    }), 422  # Unprocessable Entity
            
            download_duration = time.time() - download_start
            logger.info(f"Download concluído: {downloaded:,} bytes em {download_duration:.2f}s")
            
            # ANÁLISE COM LOGGING DETALHADO
            analysis_start = time.time()
            
            try:
                # Verificar se PyMuPDF está disponível
                try:
                    import fitz
                except ImportError as fitz_error:
                    logger.warning(f"PyMuPDF não encontrado: {fitz_error}")
                    raise ImportError("PyMuPDF não disponível") from fitz_error
                    
                color_stats = analyze_pdf_colors(temp_path)
                analysis_method = 'PyMuPDF_precise'
                logger.info(f"Análise PyMuPDF concluída: {color_stats}")
                
            except ImportError:
                # Fallback para análise básica se PyMuPDF não disponível
                logger.warning("PyMuPDF não disponível, usando fallback PyPDF2")
                with open(temp_path, 'rb') as pdf_file:
                    pdf_reader = PyPDF2.PdfReader(pdf_file)
                    total_pages = len(pdf_reader.pages)
                    # Estimativa conservadora: 30% colorido
                    color_pages = max(1, int(total_pages * 0.3))
                    mono_pages = total_pages - color_pages
                    
                color_stats = {
                    'total_pages': total_pages,
                    'color_pages': color_pages,
                    'mono_pages': mono_pages,
                    'color_type': 'mixed' if color_pages > 0 else 'mono'
                }
                analysis_method = 'PyPDF2_estimate'
            
            analysis_duration = time.time() - analysis_start
            total_duration = time.time() - operation_start
            
            # Log de performance estruturado
            log_api_performance(
                operation='pdf_analysis_url',
                duration=total_duration,
                file_size=downloaded,
                success=True
            )
            
            logger.info(
                f"Análise completa - Método: {analysis_method}, "
                f"Arquivo: {downloaded/1024:.1f}KB, "
                f"Download: {download_duration:.2f}s, "
                f"Análise: {analysis_duration:.2f}s, "
                f"Total: {total_duration:.2f}s"
            )
            
            # Retornar dados de análise com metadados de performance
            return jsonify({
                'success': True,
                'data': {
                    'total_pages': color_stats['total_pages'],
                    'color_pages': color_stats['color_pages'], 
                    'mono_pages': color_stats['mono_pages'],
                    'color_type': color_stats['color_type'],
                    'analysis_method': analysis_method,
                    'file_size_bytes': downloaded,
                    'processing_time_seconds': round(total_duration, 2)
                },
                'message': f'PDF analisado com sucesso via {analysis_method} em {total_duration:.1f}s'
            }), 200
            
            # Context manager garante cleanup automático
    
    except Exception as e:
        print(f"[ERROR] Erro na análise PDF via URL: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erro interno: {str(e)}',
            'error_code': 'INTERNAL_ERROR'
        }), 500

# ============================================
# WORKER THREAD PARA PROCESSAMENTO ASSÍNCRONO - PRIORIDADE 1
# ============================================

def process_pdf_analysis_job(job):
    """
    Processa um job de análise de PDF - extraído da lógica síncrona
    """
    try:
        # Parse dos dados de entrada
        input_data = json.loads(job.input_data)
        pdf_url = input_data['pdf_url']
        api_key = input_data['api_key']
        file_size_hint = input_data.get('file_size_hint', 0)
        
        logger.info(f"Iniciando processamento assíncrono do job {job.id} para PDF: {pdf_url}")
        
        # Atualizar status para 'running'
        job.status = 'running'
        job.started_at = datetime.now()
        job.progress = 10
        db.session.commit()
        
        # Validações de segurança (similar ao código síncrono)
        from urllib.parse import urlparse
        import ipaddress
        
        parsed = urlparse(pdf_url)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError('URL deve usar http:// ou https://')
        
        # DOWNLOAD SEGURO (mesma lógica do código síncrono)
        operation_start = time.time()
        
        # Conectar e baixar com timeout otimizado
        connect_timeout = 5
        read_timeout = PDF_DOWNLOAD_TIMEOUT
        
        logger.info(f"Job {job.id}: Iniciando download seguro de PDF")
        response = requests.get(
            pdf_url, 
            timeout=(connect_timeout, read_timeout), 
            stream=True, 
            allow_redirects=False,
            headers={'User-Agent': 'Web2Print-Worker/1.0'}
        )
        
        if response.status_code in (301, 302, 303, 307, 308):
            raise ValueError('Redirects não são permitidos por segurança')
            
        response.raise_for_status()
        
        # Verificar Content-Type
        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('application/pdf'):
            raise ValueError(f'Content-Type inválido: {content_type}')
        
        job.progress = 20
        db.session.commit()
        
        # PROCESSAMENTO COM CONTEXT MANAGER
        with secure_temp_pdf_file() as temp_path:
            # Download em chunks com limite rígido
            downloaded = 0
            chunk_count = 0
            download_start = time.time()
            
            expected_size = response.headers.get('content-length')
            if expected_size:
                expected_size = int(expected_size)
                logger.info(f"Job {job.id}: Tamanho esperado {expected_size:,} bytes")
            
            job.progress = 30
            db.session.commit()
            
            with open(temp_path, 'wb') as temp_file:
                try:
                    for chunk in response.iter_content(chunk_size=64*1024):
                        if chunk:
                            chunk_count += 1
                            downloaded += len(chunk)
                            
                            # Limite rígido
                            if downloaded > MAX_PDF_SIZE_TOTAL:
                                raise ValueError(f'Arquivo muito grande: {downloaded/1024/1024:.1f}MB')
                            
                            temp_file.write(chunk)
                            
                            # Atualizar progresso do download (30% a 60%)
                            if chunk_count % 50 == 0:  # Atualizar a cada 50 chunks (3.2MB)
                                progress = 30 + int(30 * downloaded / MAX_PDF_SIZE_TOTAL)
                                if progress != job.progress:
                                    job.progress = min(progress, 60)
                                    db.session.commit()
                                    
                except requests.exceptions.RequestException as download_error:
                    raise ValueError(f'Erro durante download: {download_error}')
            
            download_duration = time.time() - download_start
            logger.info(f"Job {job.id}: Download concluído - {downloaded:,} bytes em {download_duration:.2f}s")
            
            job.progress = 70
            db.session.commit()
            
            # ANÁLISE DO PDF (70% a 90%)
            analysis_start = time.time()
            
            try:
                # Usar PyMuPDF
                import pymupdf as fitz
                    
                color_stats = analyze_pdf_colors(temp_path)
                analysis_method = 'PyMuPDF_precise'
                logger.info(f"Job {job.id}: Análise PyMuPDF concluída")
                
            except ImportError:
                # Fallback PyPDF2
                logger.warning(f"Job {job.id}: PyMuPDF não disponível, usando PyPDF2")
                with open(temp_path, 'rb') as pdf_file:
                    pdf_reader = PyPDF2.PdfReader(pdf_file)
                    total_pages = len(pdf_reader.pages)
                    color_pages = max(1, int(total_pages * 0.3))
                    mono_pages = total_pages - color_pages
                    
                color_stats = {
                    'total_pages': total_pages,
                    'color_pages': color_pages,
                    'mono_pages': mono_pages,
                    'color_type': 'mixed' if color_pages > 0 else 'mono'
                }
                analysis_method = 'PyPDF2_estimate'
            
            analysis_duration = time.time() - analysis_start
            total_duration = time.time() - operation_start
            
            job.progress = 90
            db.session.commit()
            
            # Preparar resultado
            result_data = {
                'total_pages': color_stats['total_pages'],
                'color_pages': color_stats['color_pages'], 
                'mono_pages': color_stats['mono_pages'],
                'color_type': color_stats['color_type'],
                'analysis_method': analysis_method,
                'file_size_bytes': downloaded,
                'processing_time_seconds': round(total_duration, 2)
            }
            
            # Finalizar job
            job.status = 'completed'
            job.progress = 100
            job.completed_at = datetime.now()
            job.result_data = json.dumps(result_data)
            db.session.commit()
            
            logger.info(
                f"Job {job.id} CONCLUÍDO - Método: {analysis_method}, "
                f"Arquivo: {downloaded/1024:.1f}KB, Total: {total_duration:.2f}s"
            )
            
            # Log de performance
            log_api_performance(
                operation=f'pdf_analysis_async_{job.id}',
                duration=total_duration,
                file_size=downloaded,
                success=True
            )
            
    except Exception as e:
        # Marcar job como falhado
        job.status = 'failed'
        job.completed_at = datetime.now()
        job.error_message = str(e)
        db.session.commit()
        
        logger.error(f"Job {job.id} FALHOU: {str(e)}")
        
        # Calcular duração se start_time estiver disponível no contexto da função
        job_duration = 0
        if 'operation_start' in locals():
            job_duration = time.time() - operation_start
        elif hasattr(job, 'started_at') and job.started_at:
            job_duration = (datetime.now() - job.started_at).total_seconds()
        
        log_api_performance(
            operation=f'pdf_analysis_async_{job.id}',
            duration=job_duration,
            file_size=0,
            success=False
        )

def async_worker():
    """
    Worker thread que processa jobs pendentes continuamente
    """
    logger.info("Worker assíncrono iniciado")
    
    while True:
        try:
            # CRÍTICO: Flask context necessário para acessar banco de dados
            with app.app_context():
                # Buscar próximo job pendente
                job = Job.query.filter_by(status='pending').order_by(Job.created_at).first()
            
                if job:
                    # Verificar se não expirou
                    if job.expires_at < datetime.now():
                        logger.info(f"Job expirado removido pelo worker: {job.id}")
                        db.session.delete(job)
                        db.session.commit()
                        continue
                    
                    # Processar job
                    if job.job_type == 'pdf_analysis_url':
                        process_pdf_analysis_job(job)
                    else:
                        logger.warning(f"Tipo de job desconhecido: {job.job_type}")
                        job.status = 'failed'
                        job.error_message = f'Tipo de job não suportado: {job.job_type}'
                        db.session.commit()
                else:
                    # Sem jobs pendentes, aguardar
                    time.sleep(2)
                
        except Exception as e:
            logger.error(f"Erro no worker assíncrono: {str(e)}")
            time.sleep(5)  # Aguardar mais em caso de erro

# Iniciar worker thread em background
worker_thread = threading.Thread(target=async_worker, daemon=True)
worker_thread.start()

logger.info("Sistema assíncrono inicializado - worker thread iniciado")

# ============================================
# ENDPOINT PARA POLLING DE JOBS ASSÍNCRONOS - PRIORIDADE 1
# ============================================

@app.route('/api/v1/jobs/<job_id>', methods=['GET', 'OPTIONS'])
@csrf.exempt
def api_get_job_status(job_id):
    """
    Endpoint para consultar status de jobs assíncronos via polling
    
    GET /api/v1/jobs/<job_id>
    Response:
    - 200: Job encontrado (pending, running, completed, failed)
    - 404: Job não encontrado ou expirado
    - 410: Job expirado (Gone)
    """
    # CORS headers para WordPress
    if request.method == 'OPTIONS':
        return '', 200, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, X-API-Key',
        }
    
    try:
        # Buscar job no banco
        job = Job.query.filter_by(id=job_id).first()
        
        if not job:
            return jsonify({
                'success': False,
                'error': 'Job não encontrado',
                'error_code': 'JOB_NOT_FOUND'
            }), 404
        
        # Verificar se job expirou
        if job.expires_at < datetime.now():
            logger.info(f"Job expirado removido: {job_id}")
            db.session.delete(job)
            db.session.commit()
            return jsonify({
                'success': False,
                'error': 'Job expirado',
                'error_code': 'JOB_EXPIRED'
            }), 410  # Gone
        
        # Preparar resposta baseada no status
        response_data = {
            'job_id': job.id,
            'status': job.status,
            'progress': job.progress,
            'created_at': job.created_at.isoformat(),
        }
        
        # Adicionar dados específicos por status
        if job.status == 'pending':
            response_data.update({
                'message': 'Job aguardando processamento',
                'estimated_time_seconds': 45
            })
            
        elif job.status == 'running':
            response_data.update({
                'message': f'Processando PDF... {job.progress}%',
                'started_at': job.started_at.isoformat() if job.started_at else None
            })
            
        elif job.status == 'completed':
            # Job concluído - retornar resultado
            result_data = json.loads(job.result_data) if job.result_data else {}
            response_data.update({
                'success': True,
                'message': 'PDF processado com sucesso',
                'completed_at': job.completed_at.isoformat() if job.completed_at else None,
                'data': result_data
            })
            
        elif job.status == 'failed':
            response_data.update({
                'success': False,
                'message': 'Falha no processamento do PDF',
                'error': job.error_message,
                'completed_at': job.completed_at.isoformat() if job.completed_at else None
            })
        
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Erro ao consultar job {job_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Erro interno do servidor',
            'error_code': 'INTERNAL_ERROR'
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

            # Validar formato do CEP (apenas dígitos, 5 ou 8 dígitos, com ou sem hífen)
            import re
            cep_clean = re.sub(r'[^0-9]', '', cep)
            if not re.match(r'^\d{8}$', cep_clean):
                return render_template('register.html', error='CEP deve conter exatamente 8 dígitos')

            # Verificar se o CPF já existe
            existing_user = User.query.filter_by(cpf=cpf).first()
            if existing_user:
                return render_template('register.html', error='CPF já cadastrado')

            # Buscar endereço a partir do CEP (usando CEP validado)
            try:
                response = requests.get(f'https://viacep.com.br/ws/{cep_clean}/json/', timeout=10)
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
