import os
import sqlite3
import json
import math
import urllib.request
import urllib.parse
import logging
from datetime import datetime, date
from flask import Flask, request, jsonify, g, send_from_directory

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('SmartDiet')
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder='static')
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'smartdiet_production.db')

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/')
def serve_index():
    logger.debug("Servindo index.html")
    return send_from_directory('static', 'index.html')

# ==============================================================================
# BANCO DE DADOS
# ==============================================================================
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        logger.debug("Abrindo nova conexão com banco de dados")
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def init_db():
    """Inicializa schema relacional robusto com suporte a logs de refeições."""
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        cursor.executescript('''
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT CHECK(role IN ('admin', 'consumer', 'nutritionist', 'market')) NOT NULL,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login DATETIME,
                is_active BOOLEAN DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                phone TEXT,
                document TEXT,
                address TEXT,
                cep TEXT,
                lat REAL,
                lng REAL,
                avatar_url TEXT,
                weight_kg REAL,
                height_cm REAL,
                goal TEXT,
                nutritionist_id INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(nutritionist_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS tags_restrictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT UNIQUE NOT NULL,
                description TEXT,
                severity_level INTEGER DEFAULT 1,
                icon TEXT DEFAULT 'fa-circle-exclamation',
                color TEXT DEFAULT 'orange'
            );

            CREATE TABLE IF NOT EXISTS user_restrictions (
                user_id INTEGER,
                tag_id INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES tags_restrictions(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, tag_id)
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT UNIQUE,
                barcode TEXT UNIQUE,
                name TEXT NOT NULL,
                brand TEXT,
                category TEXT NOT NULL,
                nutritional_info TEXT, -- json: kcal, prot, carb, fat
                base_price REAL,
                image_url TEXT,
                is_active BOOLEAN DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS product_tags (
                product_id INTEGER,
                tag_id INTEGER,
                is_compliant BOOLEAN DEFAULT 1,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES tags_restrictions(id) ON DELETE CASCADE,
                PRIMARY KEY (product_id, tag_id)
            );

            CREATE TABLE IF NOT EXISTS markets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                brand_name TEXT NOT NULL,
                branch_name TEXT NOT NULL,
                address TEXT,
                lat REAL,
                lng REAL,
                markup_multiplier REAL DEFAULT 1.0,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY(owner_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS inventory (
                market_id INTEGER,
                product_id INTEGER,
                stock_qty INTEGER DEFAULT 0,
                current_price REAL,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(market_id) REFERENCES markets(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
                PRIMARY KEY (market_id, product_id)
            );

            CREATE TABLE IF NOT EXISTS diets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER,
                nutritionist_id INTEGER,
                title TEXT NOT NULL,
                target_kcal INTEGER,
                target_protein INTEGER,
                target_carbs INTEGER,
                target_fat INTEGER,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY(patient_id) REFERENCES users(id),
                FOREIGN KEY(nutritionist_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS diet_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                diet_id INTEGER,
                meal_name TEXT NOT NULL,
                meal_time TEXT,
                meal_order INTEGER DEFAULT 0,
                product_category TEXT,
                recommended_product_id INTEGER,
                qty_grams INTEGER,
                FOREIGN KEY(diet_id) REFERENCES diets(id) ON DELETE CASCADE,
                FOREIGN KEY(recommended_product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS meal_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                diet_item_id INTEGER NOT NULL,
                logged_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                log_date DATE DEFAULT (date('now')),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(diet_item_id) REFERENCES diet_items(id) ON DELETE CASCADE,
                UNIQUE(user_id, diet_item_id, log_date)
            );
        ''')

        if not cursor.execute("SELECT id FROM users LIMIT 1").fetchone():
            _seed_database(cursor)

        db.commit()


def _seed_database(cursor):
    """Popula o banco com dados ricos para todos os agentes econômicos da plataforma."""
    pwd = generate_password_hash('123456')

    # Usuários
    cursor.executemany("INSERT INTO users (id, role, name, email, password_hash) VALUES (?, ?, ?, ?, ?)", [
        (1, 'admin',        'Administrador Global',          'admin@smartdiet.com',    pwd),
        (2, 'consumer',     'André Suhai',                   'paciente@demo.com',      pwd),
        (3, 'nutritionist', 'Dra. Sarah Mello (CRN 9999)',   'sarah@nutri.com',        pwd),
        (4, 'market',       'Gestor Pão de Açúcar',          'gestor@pda.com',         pwd),
        (5, 'market',       'Gestor Mundo Verde',            'gestor@mundoverde.com',  pwd),
        (6, 'consumer',     'Camila Torres',                 'camila@demo.com',        pwd),
        (7, 'consumer',     'Bruno Lima',                    'bruno@demo.com',         pwd),
    ])

    # Perfis
    cursor.executemany("INSERT INTO user_profiles (user_id, cep, lat, lng, weight_kg, height_cm, goal, nutritionist_id, avatar_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (2, '04546042', -23.598, -46.676, 82.0, 180.0, 'Hipertrofia Muscular', 3, 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=200&q=80'),
        (3, '01310100', -23.561, -46.656, 62.0, 168.0, 'Nutrição Clínica & Esportiva', None, 'https://images.unsplash.com/photo-1559839734-2b71ea197ec2?auto=format&fit=crop&w=200&q=80'),
        (4, '01452000', -23.585, -46.678, 75.0, 175.0, 'Gestão de Vendas', None, 'https://images.unsplash.com/photo-1560250097-0b93528c311a?auto=format&fit=crop&w=200&q=80'),
        (6, '05407000', -23.560, -46.680, 58.0, 164.0, 'Emagrecimento & Definição', 3, 'https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&w=200&q=80'),
        (7, '04012000', -23.590, -46.640, 88.0, 185.0, 'Performance & Low Carb', 3, 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=200&q=80'),
    ])

    # Restrições / Tags Clínicas
    tags = [
        (1, 'Zero Lactose',  'Sem derivados de leite (intolerância ou alergia)', 3, 'fa-droplet-slash', 'orange'),
        (2, 'Sem Glúten',    'Celíacos ou sensibilidade a trigo/centeio',        3, 'fa-wheat-awn-circle-exclamation', 'yellow'),
        (3, 'Vegano',        '100% livre de ingredientes de origem animal',       2, 'fa-seedling', 'green'),
        (4, 'Hipertrofia',   'Densidade proteica alta (>20g por porção)',         1, 'fa-dumbbell', 'blue'),
        (5, 'Low Carb',      'Baixo carboidrato líquido e baixo índice glicêmico',1, 'fa-chart-line', 'purple'),
        (6, 'Zero Açúcar',   'Sem açúcares adicionados (diabéticos / cetogênica)',2, 'fa-ban', 'red'),
        (7, 'Orgânico',      'Certificação orgânica livre de agrotóxicos',        1, 'fa-leaf', 'green'),
    ]
    cursor.executemany("INSERT INTO tags_restrictions (id, tag_name, description, severity_level, icon, color) VALUES (?, ?, ?, ?, ?, ?)", tags)

    # Restrições dos Pacientes
    cursor.executemany("INSERT INTO user_restrictions (user_id, tag_id) VALUES (?, ?)", [
        (2, 1), (2, 2), (2, 4), # André: Zero Lactose, Sem Glúten, Hipertrofia
        (6, 1), (6, 3), (6, 6), # Camila: Zero Lactose, Vegano, Zero Açúcar
        (7, 2), (7, 5),         # Bruno: Sem Glúten, Low Carb
    ])

    # Catálogo de Produtos Expandido (Base 100g padrão para cálculo de precisão nutricional)
    prods = [
        (1, 'SKU001', '78910001', 'Whey Protein Isolado Dux 900g',    'Dux',         'Suplementos',        json.dumps({'kcal': 380, 'prot': 80, 'carb': 5,   'fat': 2}),   199.90, 'https://images.unsplash.com/photo-1593095948071-474c5cc2989d?auto=format&fit=crop&w=200&q=80'),
        (2, 'SKU002', '78910002', 'Pão de Forma S/ Glúten Schar',     'Schar',       'Padaria',            json.dumps({'kcal': 240, 'prot': 4,  'carb': 48,  'fat': 3.5}),  24.50, 'https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=200&q=80'),
        (3, 'SKU003', '78910003', 'Leite de Amêndoas Silk 1L',        'Silk',        'Laticínios Veganos',  json.dumps({'kcal': 35,  'prot': 1.2,'carb': 3,   'fat': 2.5}),  19.90, 'https://images.unsplash.com/photo-1550583724-b2692b85b150?auto=format&fit=crop&w=200&q=80'),
        (4, 'SKU004', '78910004', 'Peito de Frango Resfriado 1kg',    'Seara',       'Carnes',             json.dumps({'kcal': 140, 'prot': 28, 'carb': 0,   'fat': 2.5}),  22.90, 'https://images.unsplash.com/photo-1604503468506-a8da13d11d36?auto=format&fit=crop&w=200&q=80'),
        (5, 'SKU005', '78910005', 'Aveia em Flocos S/ Glúten 500g',   'Quaker',      'Cereais',            json.dumps({'kcal': 365, 'prot': 14, 'carb': 62,  'fat': 7}),    14.90, 'https://images.unsplash.com/photo-1495214783159-3503fd1b572d?auto=format&fit=crop&w=200&q=80'),
        (6, 'SKU006', '78910006', 'Pasta de Amendoim Integral 500g',  'Power1',      'Lanches',            json.dumps({'kcal': 590, 'prot': 26, 'carb': 18,  'fat': 50}),   18.00, 'https://images.unsplash.com/photo-1608571423902-eed4a5ad8108?auto=format&fit=crop&w=200&q=80'),
        (7, 'SKU007', '78910007', 'Iogurte Proteico Zero Lactose',    'Verde Campo', 'Laticínios',        json.dumps({'kcal': 68,  'prot': 10, 'carb': 5,   'fat': 0.5}),   7.50, 'https://images.unsplash.com/photo-1488477181946-6428a0291777?auto=format&fit=crop&w=200&q=80'),
        (8, 'SKU008', '78910008', 'Batata Doce Branca 1kg',           'Hortifruti',  'Vegetais',           json.dumps({'kcal': 86,  'prot': 1.6,'carb': 20,  'fat': 0.1}),   5.90, 'https://images.unsplash.com/photo-1596097635232-7ba7c9fe92fe?auto=format&fit=crop&w=200&q=80'),
        (9, 'SKU009', '78910009', 'Ovos Caipiras Orgânicos 12un',     'Sítio Bom',   'Proteínas',         json.dumps({'kcal': 145, 'prot': 13, 'carb': 1,   'fat': 10}),   16.90, 'https://images.unsplash.com/photo-1506976785307-8732e854ad03?auto=format&fit=crop&w=200&q=80'),
        (10,'SKU010', '78910010', 'Brócolis Orgânico 500g',           'Hortifruti',  'Vegetais',           json.dumps({'kcal': 35,  'prot': 3,  'carb': 7,   'fat': 0.4}),   9.90, 'https://images.unsplash.com/photo-1459411621453-7b03977f4bfc?auto=format&fit=crop&w=200&q=80'),
        (11,'SKU011', '78910011', 'Tofu Orgânico Firme 400g',         'Agronature',  'Laticínios Veganos',  json.dumps({'kcal': 85,  'prot': 10, 'carb': 2,   'fat': 5}),    17.90, 'https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=200&q=80'),
        (12,'SKU012', '78910012', 'Filé de Salmão Fresco 500g',       'Costa Sul',   'Carnes',             json.dumps({'kcal': 208, 'prot': 20, 'carb': 0,   'fat': 13}),   48.90, 'https://images.unsplash.com/photo-1467003909585-2f8a72700288?auto=format&fit=crop&w=200&q=80'),
        (13,'SKU013', '78910013', 'Arroz Integral Cateto 1kg',        'Camil',       'Cereais',            json.dumps({'kcal': 130, 'prot': 3,  'carb': 28,  'fat': 1}),     8.50, 'https://images.unsplash.com/photo-1586201375761-83865001e31c?auto=format&fit=crop&w=200&q=80'),
        (14,'SKU014', '78910014', 'Mix de Castanhas Nobres 200g',     'Mundo Verde', 'Lanches',            json.dumps({'kcal': 610, 'prot': 18, 'carb': 16,  'fat': 54}),   22.90, 'https://images.unsplash.com/photo-1509722747041-616f39b57569?auto=format&fit=crop&w=200&q=80'),
        (15,'SKU015', '78910015', 'Banana Prata Orgânica 1kg',        'Hortifruti',  'Vegetais',           json.dumps({'kcal': 90,  'prot': 1.3,'carb': 23,  'fat': 0.3}),   8.90, 'https://images.unsplash.com/photo-1571771894821-ce9b6c11b08e?auto=format&fit=crop&w=200&q=80'),
    ]
    cursor.executemany("INSERT INTO products (id, sku, barcode, name, brand, category, nutritional_info, base_price, image_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", prods)

    # Mapeamento Produto x Tags
    cursor.executescript('''
        INSERT INTO product_tags (product_id, tag_id) VALUES
        (1,1),(1,2),(1,4),(1,6),
        (2,1),(2,2),(2,3),
        (3,1),(3,2),(3,3),(3,6),
        (4,1),(4,2),(4,4),(4,5),(4,6),
        (5,1),(5,2),(5,3),(5,7),
        (6,1),(6,2),(6,3),(6,4),(6,6),
        (7,1),(7,2),(7,4),(7,6),
        (8,1),(8,2),(8,3),(8,5),(8,7),
        (9,1),(9,2),(9,4),(9,5),(9,7),
        (10,1),(10,2),(10,3),(10,5),(10,6),(10,7),
        (11,1),(11,2),(11,3),(11,4),(11,5),(11,6),(11,7),
        (12,1),(12,2),(12,4),(12,5),(12,6),
        (13,1),(13,2),(13,3),(13,7),
        (14,1),(14,2),(14,3),(14,5),(14,6),
        (15,1),(15,2),(15,3),(15,7);
    ''')

    # Dieta ativa de André Suhai (Paciente 2 - Hipertrofia Muscular & Bulking Limpo)
    cursor.execute("""
        INSERT INTO diets (id, patient_id, nutritionist_id, title, target_kcal, target_protein, target_carbs, target_fat, notes)
        VALUES (1, 2, 3, 'Plano Hipertrofia — Fase Bulking Limpo', 2150, 160, 220, 65,
        'Foco em superávit calórico controlado, alta biodisponibilidade proteica e digestibilidade ótima. 100% livre de glúten e lactose.')
    """)

    cursor.executemany("""
        INSERT INTO diet_items (diet_id, meal_name, meal_time, meal_order, product_category, recommended_product_id, qty_grams)
        VALUES (1, ?, ?, ?, ?, ?, ?)
    """, [
        ('Café da Manhã',           '07:30', 1, 'Proteínas',          9,  150), # Ovos Caipiras (150g ~ 3 ovos) -> 218 kcal, 20g P, 1g C, 15g F
        ('Acompanhamento Café',     '07:30', 2, 'Cereais',            5,   70), # Aveia S/ Glúten (70g) -> 255 kcal, 10g P, 43g C, 5g F
        ('Shake Pós-Treino',        '10:00', 3, 'Suplementos',        1,   40), # Whey Isolado (40g) -> 152 kcal, 32g P, 2g C, 0.8g F
        ('Almoço Anabólico',        '13:00', 4, 'Carnes',             4,  180), # Peito Frango (180g) -> 252 kcal, 50g P, 0g C, 4.5g F
        ('Carboidrato Almoço',      '13:00', 5, 'Cereais',           13,  220), # Arroz Integral (220g) -> 286 kcal, 6.6g P, 61.6g C, 2.2g F
        ('Lanche da Tarde',         '16:30', 6, 'Laticínios',         7,  200), # Iogurte Proteico (200g) -> 136 kcal, 20g P, 10g C, 1g F
        ('Gorduras Boas Tarde',     '16:30', 7, 'Lanches',            6,   30), # Pasta de Amendoim (30g) -> 177 kcal, 7.8g P, 5.4g C, 15g F
        ('Jantar Regenerativo',     '20:00', 8, 'Carnes',            12,  160), # Filé de Salmão (160g) -> 333 kcal, 32g P, 0g C, 20.8g F
        ('Carboidrato Jantar',      '20:00', 9, 'Vegetais',           8,  250), # Batata Doce (250g) -> 215 kcal, 4g P, 50g C, 0.2g F
    ])

    # Dieta de Camila Torres (Paciente 6 - Plant-Based)
    cursor.execute("""
        INSERT INTO diets (id, patient_id, nutritionist_id, title, target_kcal, target_protein, target_carbs, target_fat, notes)
        VALUES (2, 6, 3, 'Protocolo Plant-Based & Definição', 1650, 110, 180, 45,
        'Dieta 100% vegana, rica em leguminosas, fitoquímicos e fontes integrais de energia.')
    """)
    cursor.executemany("""
        INSERT INTO diet_items (diet_id, meal_name, meal_time, meal_order, product_category, recommended_product_id, qty_grams)
        VALUES (2, ?, ?, ?, ?, ?, ?)
    """, [
        ('Café da Manhã',    '07:30', 1, 'Laticínios Veganos',  3,  250), # Leite de Amêndoas (250g)
        ('Acompanhamento',   '07:30', 2, 'Cereais',            5,   60), # Aveia (60g)
        ('Almoço Vegano',    '12:30', 3, 'Laticínios Veganos', 11,  200), # Tofu Firme (200g)
        ('Carboidrato Almoço','12:30',4, 'Cereais',           13,  200), # Arroz Integral (200g)
        ('Lanche da Tarde',  '16:00', 5, 'Lanches',            14,   35), # Castanhas (35g)
        ('Jantar Funcional', '19:30', 6, 'Vegetais',           10,  200), # Brócolis (200g)
        ('Carboidrato Jantar','19:30',7, 'Vegetais',            8,  180), # Batata Doce (180g)
    ])


# ==============================================================================
# CORS
# ==============================================================================
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

@app.route('/api/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    return '', 204


# ==============================================================================
# AUTH
# ==============================================================================
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    db = get_db()
    db.row_factory = dict_factory
    user = db.execute(
        "SELECT id, role, name, email, password_hash FROM users WHERE email = ?",
        (data.get('email'),)
    ).fetchone()

    if user and check_password_hash(user['password_hash'], data.get('password', '')):
        db.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
        db.commit()
        return jsonify({
            'status': 'success',
            'token': f"jwt_mock_{user['id']}_{user['role']}",
            'user': {'id': user['id'], 'name': user['name'], 'role': user['role'], 'email': user['email']}
        })
    return jsonify({'status': 'error', 'message': 'Credenciais inválidas. Verifique e-mail e senha.'}), 401


# ==============================================================================
# CONSUMER ENDPOINTS
# ==============================================================================
@app.route('/api/consumer/profile', methods=['GET'])
def get_consumer_profile():
    user_id = request.args.get('user_id', 2)
    db = get_db()
    db.row_factory = dict_factory

    user = db.execute("SELECT id, name, email, role, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    profile = db.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    restrictions = db.execute('''
        SELECT t.id, t.tag_name, t.icon, t.color, t.description
        FROM user_restrictions ur
        JOIN tags_restrictions t ON ur.tag_id = t.id
        WHERE ur.user_id = ?
    ''', (user_id,)).fetchall()

    return jsonify({
        'user': user,
        'profile': profile,
        'restrictions': restrictions
    })

@app.route('/api/consumer/profile/update', methods=['POST'])
def update_consumer_profile():
    data = request.json
    user_id = data.get('user_id')
    cep = data.get('cep')
    if not user_id:
        return jsonify({'status': 'error', 'message': 'Missing user_id'}), 400
    
    db = get_db()
    db.execute("UPDATE user_profiles SET cep = ? WHERE user_id = ?", (cep, user_id))
    db.commit()
    return jsonify({'status': 'success', 'message': 'Perfil atualizado.'})


@app.route('/api/consumer/diet', methods=['GET'])
def get_consumer_diet():
    user_id = request.args.get('user_id', 2)
    today = date.today().isoformat()
    db = get_db()
    db.row_factory = dict_factory

    restrictions = db.execute('''
        SELECT t.id, t.tag_name, t.icon, t.color, t.description
        FROM user_restrictions ur
        JOIN tags_restrictions t ON ur.tag_id = t.id
        WHERE ur.user_id = ?
    ''', (user_id,)).fetchall()

    diet = db.execute(
        "SELECT * FROM diets WHERE patient_id = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
        (user_id,)
    ).fetchone()

    diet_items = []
    if diet:
        items_raw = db.execute('''
            SELECT di.*,
                   p.name as product_name, p.brand as product_brand,
                   p.category, p.nutritional_info, p.image_url, p.base_price
            FROM diet_items di
            LEFT JOIN products p ON di.recommended_product_id = p.id
            WHERE di.diet_id = ?
            ORDER BY di.meal_order
        ''', (diet['id'],)).fetchall()

        logged_ids = set(row['diet_item_id'] for row in db.execute(
            "SELECT diet_item_id FROM meal_logs WHERE user_id = ? AND log_date = ?",
            (user_id, today)
        ).fetchall())

        for item in items_raw:
            item['nutritional_info'] = json.loads(item['nutritional_info']) if item['nutritional_info'] else {}
            item['checked'] = item['id'] in logged_ids
            diet_items.append(item)

    return jsonify({
        'restrictions': restrictions,
        'diet_plan': diet,
        'diet_items': diet_items
    })


@app.route('/api/consumer/progress', methods=['GET'])
def get_consumer_progress():
    user_id = request.args.get('user_id', 2)
    today = date.today().isoformat()
    db = get_db()
    db.row_factory = dict_factory

    diet = db.execute(
        "SELECT id, target_kcal, target_protein, target_carbs, target_fat FROM diets WHERE patient_id = ? AND is_active = 1 LIMIT 1",
        (user_id,)
    ).fetchone()

    if not diet:
        return jsonify({'kcal_consumed': 0, 'kcal_target': 2000, 'prot_consumed': 0, 'prot_target': 150, 'carb_consumed': 0, 'carb_target': 200, 'fat_consumed': 0, 'fat_target': 60, 'meals_done': 0, 'meals_total': 0, 'streak': 5})

    logged = db.execute('''
        SELECT SUM(CAST(json_extract(p.nutritional_info, '$.kcal') AS REAL) * di.qty_grams / 100.0) as kcal,
               SUM(CAST(json_extract(p.nutritional_info, '$.prot') AS REAL) * di.qty_grams / 100.0) as prot,
               SUM(CAST(json_extract(p.nutritional_info, '$.carb') AS REAL) * di.qty_grams / 100.0) as carb,
               SUM(CAST(json_extract(p.nutritional_info, '$.fat')  AS REAL) * di.qty_grams / 100.0) as fat,
               COUNT(*) as count
        FROM meal_logs ml
        JOIN diet_items di ON ml.diet_item_id = di.id
        JOIN products p ON di.recommended_product_id = p.id
        WHERE ml.user_id = ? AND ml.log_date = ?
    ''', (user_id, today)).fetchone()

    total_meals = db.execute(
        "SELECT COUNT(*) as cnt FROM diet_items WHERE diet_id = ?", (diet['id'],)
    ).fetchone()['cnt']

    return jsonify({
        'kcal_consumed': round(logged['kcal'] or 0, 0),
        'kcal_target': diet['target_kcal'] or 2150,
        'prot_consumed': round(logged['prot'] or 0, 1),
        'prot_target': diet['target_protein'] or 160,
        'carb_consumed': round(logged['carb'] or 0, 1),
        'carb_target': diet['target_carbs'] or 220,
        'fat_consumed': round(logged['fat'] or 0, 1),
        'fat_target': diet['target_fat'] or 65,
        'meals_done': logged['count'] or 0,
        'meals_total': total_meals,
        'streak': 7
    })


@app.route('/api/consumer/meal/check', methods=['POST'])
def check_meal():
    data = request.json
    user_id = data.get('user_id', 2)
    diet_item_id = data.get('diet_item_id')
    checked = data.get('checked', True)
    today = date.today().isoformat()

    db = get_db()
    if checked:
        try:
            db.execute(
                "INSERT OR IGNORE INTO meal_logs (user_id, diet_item_id, log_date) VALUES (?, ?, ?)",
                (user_id, diet_item_id, today)
            )
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
    else:
        db.execute(
            "DELETE FROM meal_logs WHERE user_id = ? AND diet_item_id = ? AND log_date = ?",
            (user_id, diet_item_id, today)
        )

    db.commit()
    return jsonify({'status': 'success', 'checked': checked})


@app.route('/api/consumer/order/delivery', methods=['POST'])
def place_delivery_order():
    """Simula a finalização de compras otimizada com entrega expressa direto no endereço do usuário."""
    data = request.json or {}
    user_id = data.get('user_id', 2)
    market_id = data.get('market_id')
    market_name = data.get('market_name', 'Pão de Açúcar (Clodomiro Amazonas)')
    address = data.get('address', 'Rua Tabapuã, 1123 - Itaim Bibi, São Paulo - SP')
    total_price = float(data.get('total_price', 0))
    items_count = int(data.get('items_count', 9))

    import random
    order_id = f"SD-{random.randint(10000, 99999)}"
    couriers = [
        {"name": "Carlos Eduardo", "vehicle": "Honda CG 160 Cargo (Eco)", "plate": "BRA-2E19", "rating": 4.9},
        {"name": "Marcos Vinícius", "vehicle": "Yamaha Factor 150", "plate": "SPX-9A44", "rating": 5.0},
        {"name": "Juliana Santos", "vehicle": "Bicicleta Elétrica Caloi", "plate": "ECO-102", "rating": 4.95}
    ]
    courier = random.choice(couriers)
    estimated_mins = random.randint(25, 35)
    savings = round(total_price * 0.14, 2)

    return jsonify({
        'status': 'success',
        'order_id': order_id,
        'market_name': market_name,
        'estimated_minutes': estimated_mins,
        'courier': courier,
        'delivery_address': address,
        'items_count': items_count,
        'savings_reais': savings,
        'total_paid': total_price,
        'message': 'Pedido de delivery inteligente despachado com sucesso!'
    })


# ==============================================================================
# NUTRITIONIST (PRESCRIBER) ENDPOINTS
# ==============================================================================
@app.route('/api/nutritionist/patients', methods=['GET'])
def get_nutritionist_patients():
    """Lista todos os pacientes sob cuidado da nutricionista."""
    nutri_id = request.args.get('nutri_id', 3)
    db = get_db()
    db.row_factory = dict_factory

    patients = db.execute('''
        SELECT u.id, u.name, u.email,
               up.weight_kg, up.height_cm, up.goal, up.avatar_url,
               d.id as active_diet_id, d.title as active_diet_title,
               d.target_kcal, d.target_protein, d.target_carbs, d.target_fat
        FROM users u
        LEFT JOIN user_profiles up ON u.id = up.user_id
        LEFT JOIN diets d ON u.id = d.patient_id AND d.is_active = 1
        WHERE u.role = 'consumer'
        ORDER BY u.name
    ''').fetchall()

    for p in patients:
        # Pega as restrições de cada paciente
        r_tags = db.execute('''
            SELECT t.id, t.tag_name, t.icon, t.color
            FROM user_restrictions ur
            JOIN tags_restrictions t ON ur.tag_id = t.id
            WHERE ur.user_id = ?
        ''', (p['id'],)).fetchall()
        p['restrictions'] = r_tags

    return jsonify({'status': 'success', 'patients': patients})


@app.route('/api/tags', methods=['GET'])
def get_all_tags():
    """Lista todas as tags e restrições clínicas disponíveis."""
    db = get_db()
    db.row_factory = dict_factory
    tags = db.execute("SELECT * FROM tags_restrictions ORDER BY severity_level DESC, tag_name ASC").fetchall()
    return jsonify({'status': 'success', 'tags': tags})


@app.route('/api/nutritionist/protocols', methods=['GET'])
def get_diet_protocols():
    """Protocolos clínicos com distribuição calórica e de macronutrientes precisas."""
    protocols = [
        {
            'id': 'hipertrofia',
            'name': 'Hipertrofia Muscular & Bulking Limpo',
            'target_kcal': 2150,
            'target_protein': 160,
            'target_carbs': 220,
            'target_fat': 65,
            'goal': 'Hipertrofia Muscular',
            'recommended_tags': [1, 2, 4], # Zero Lactose, Sem Glúten, Hipertrofia
            'notes': 'Superávit calórico limpo com alta biodisponibilidade de aminoácidos, proteínas magras e carboidratos complexos.',
            'meals': [
                {'meal_name': 'Café da Manhã (Ovos)',       'meal_time': '07:30', 'product_id': 9,  'qty_grams': 150}, # 218 kcal, 20g P, 1g C, 15g F
                {'meal_name': 'Acompanhamento Café',        'meal_time': '07:30', 'product_id': 5,  'qty_grams': 70},  # 255 kcal, 10g P, 43g C, 5g F
                {'meal_name': 'Shake Pós-Treino',           'meal_time': '10:00', 'product_id': 1,  'qty_grams': 40},  # 152 kcal, 32g P, 2g C, 0.8g F
                {'meal_name': 'Almoço (Peito de Frango)',   'meal_time': '13:00', 'product_id': 4,  'qty_grams': 180}, # 252 kcal, 50g P, 0g C, 4.5g F
                {'meal_name': 'Carboidrato Almoço',         'meal_time': '13:00', 'product_id': 13, 'qty_grams': 220}, # 286 kcal, 6.6g P, 61.6g C, 2.2g F
                {'meal_name': 'Lanche da Tarde',            'meal_time': '16:30', 'product_id': 7,  'qty_grams': 200}, # 136 kcal, 20g P, 10g C, 1g F
                {'meal_name': 'Gorduras Boas Tarde',        'meal_time': '16:30', 'product_id': 6,  'qty_grams': 30},  # 177 kcal, 7.8g P, 5.4g C, 15g F
                {'meal_name': 'Jantar (Salmão Fresco)',     'meal_time': '20:00', 'product_id': 12, 'qty_grams': 160}, # 333 kcal, 32g P, 0g C, 20.8g F
                {'meal_name': 'Carboidrato Jantar',         'meal_time': '20:00', 'product_id': 8,  'qty_grams': 250}, # 215 kcal, 4g P, 50g C, 0.2g F
            ]
        },
        {
            'id': 'emagrecimento',
            'name': 'Déficit Calórico & Definição',
            'target_kcal': 1600,
            'target_protein': 130,
            'target_carbs': 140,
            'target_fat': 45,
            'goal': 'Emagrecimento & Definição',
            'recommended_tags': [1, 2, 6], # Zero Lactose, Sem Glúten, Zero Açúcar
            'notes': 'Déficit calórico estruturado com alta densidade de proteínas magras, micronutrientes e fibras.',
            'meals': [
                {'meal_name': 'Café da Manhã (Ovos)',       'meal_time': '08:00', 'product_id': 9,  'qty_grams': 100}, # 145 kcal, 13g P
                {'meal_name': 'Acompanhamento Café',        'meal_time': '08:00', 'product_id': 5,  'qty_grams': 45},  # 164 kcal, 6.3g P, 28g C
                {'meal_name': 'Almoço (Peito de Frango)',   'meal_time': '12:30', 'product_id': 4,  'qty_grams': 160}, # 224 kcal, 44.8g P
                {'meal_name': 'Carboidrato Almoço',         'meal_time': '12:30', 'product_id': 13, 'qty_grams': 150}, # 195 kcal, 42g C
                {'meal_name': 'Vegetais Almoço',            'meal_time': '12:30', 'product_id': 10, 'qty_grams': 150}, # 53 kcal, 4.5g P, 10.5g C
                {'meal_name': 'Lanche da Tarde',            'meal_time': '16:00', 'product_id': 7,  'qty_grams': 180}, # 122 kcal, 18g P
                {'meal_name': 'Castanhas Tarde',            'meal_time': '16:00', 'product_id': 14, 'qty_grams': 20},  # 122 kcal, 3.6g P, 10.8g F
                {'meal_name': 'Jantar (Salmão)',            'meal_time': '19:30', 'product_id': 12, 'qty_grams': 140}, # 291 kcal, 28g P, 18.2g F
                {'meal_name': 'Carboidrato Jantar',         'meal_time': '19:30', 'product_id': 8,  'qty_grams': 160}, # 138 kcal, 32g C
            ]
        },
        {
            'id': 'low_carb',
            'name': 'Low Carb Terapêutica / Cetogênica',
            'target_kcal': 1800,
            'target_protein': 140,
            'target_carbs': 50,
            'target_fat': 110,
            'goal': 'Performance & Low Carb',
            'recommended_tags': [1, 2, 5, 6], # Zero Lactose, Sem Glúten, Low Carb, Zero Açúcar
            'notes': 'Restrição de carboidratos com foco em lipídios anti-inflamatórios e proteínas nobres.',
            'meals': [
                {'meal_name': 'Café da Manhã (Ovos)',       'meal_time': '08:00', 'product_id': 9,  'qty_grams': 160}, # 232 kcal, 20.8g P, 16g F
                {'meal_name': 'Gorduras Café',              'meal_time': '08:00', 'product_id': 6,  'qty_grams': 30},  # 177 kcal, 7.8g P, 15g F
                {'meal_name': 'Almoço (Salmão Fresco)',     'meal_time': '12:30', 'product_id': 12, 'qty_grams': 200}, # 416 kcal, 40g P, 26g F
                {'meal_name': 'Vegetais Almoço',            'meal_time': '12:30', 'product_id': 10, 'qty_grams': 200}, # 70 kcal, 6g P, 14g C
                {'meal_name': 'Lanche (Whey Isolado)',      'meal_time': '16:30', 'product_id': 1,  'qty_grams': 35},  # 133 kcal, 28g P
                {'meal_name': 'Mix Castanhas Tarde',        'meal_time': '16:30', 'product_id': 14, 'qty_grams': 40},  # 244 kcal, 7.2g P, 21.6g F
                {'meal_name': 'Jantar (Peito de Frango)',   'meal_time': '20:00', 'product_id': 4,  'qty_grams': 180}, # 252 kcal, 50.4g P
                {'meal_name': 'Gorduras Jantar (Pasta)',    'meal_time': '20:00', 'product_id': 6,  'qty_grams': 30},  # 177 kcal, 7.8g P, 15g F
            ]
        },
        {
            'id': 'plant_based',
            'name': 'Plant-Based / Vegana Funcional',
            'target_kcal': 1900,
            'target_protein': 115,
            'target_carbs': 240,
            'target_fat': 55,
            'goal': 'Saúde & Plant-Based',
            'recommended_tags': [1, 2, 3, 7], # Zero Lactose, Sem Glúten, Vegano, Orgânico
            'notes': 'Dieta baseada em plantas, rica em leguminosas, fitoquímicos e fontes integrais de energia.',
            'meals': [
                {'meal_name': 'Café (Leite de Amêndoas)',   'meal_time': '07:30', 'product_id': 3,  'qty_grams': 250}, # 88 kcal
                {'meal_name': 'Aveia S/ Glúten',            'meal_time': '07:30', 'product_id': 5,  'qty_grams': 75},  # 274 kcal, 10.5g P, 46.5g C
                {'meal_name': 'Fruta Café (Banana)',        'meal_time': '07:30', 'product_id': 15, 'qty_grams': 120}, # 108 kcal, 27.6g C
                {'meal_name': 'Almoço (Tofu Firme)',        'meal_time': '12:30', 'product_id': 11, 'qty_grams': 220}, # 187 kcal, 22g P, 11g F
                {'meal_name': 'Carboidrato Almoço',         'meal_time': '12:30', 'product_id': 13, 'qty_grams': 250}, # 325 kcal, 7.5g P, 70g C
                {'meal_name': 'Vegetais Almoço',            'meal_time': '12:30', 'product_id': 10, 'qty_grams': 150}, # 53 kcal, 4.5g P
                {'meal_name': 'Lanche da Tarde (Pasta)',    'meal_time': '16:00', 'product_id': 6,  'qty_grams': 30},  # 177 kcal, 7.8g P, 15g F
                {'meal_name': 'Castanhas Tarde',            'meal_time': '16:00', 'product_id': 14, 'qty_grams': 30},  # 183 kcal, 5.4g P, 16.2g F
                {'meal_name': 'Jantar (Tofu Orgânico)',     'meal_time': '19:30', 'product_id': 11, 'qty_grams': 180}, # 153 kcal, 18g P, 9g F
                {'meal_name': 'Carboidrato Jantar',         'meal_time': '19:30', 'product_id': 8,  'qty_grams': 240}, # 206 kcal, 3.8g P, 48g C
            ]
        }
    ]
    return jsonify({'status': 'success', 'protocols': protocols})


@app.route('/api/nutritionist/generate_meals', methods=['POST'])
def generate_clinical_meals():
    """Gera um plano alimentar inteligente baseado nas especificidades exatas do paciente."""
    data = request.json or {}
    goal = data.get('goal', 'Hipertrofia Muscular').lower()
    target_kcal = int(data.get('target_kcal', 2150))
    restrictions = set(int(t) for t in data.get('restriction_tag_ids', []))

    db = get_db()
    db.row_factory = dict_factory
    products = db.execute("SELECT * FROM products WHERE is_active = 1").fetchall()
    prod_map = {p['id']: p for p in products}

    # Protocolos base otimizados
    if 'hipertrofia' in goal or 'bulking' in goal or 'massa' in goal:
        base_meals = [
            {'meal_name': 'Café da Manhã (Ovos)',       'meal_time': '07:30', 'product_id': 9,  'qty_grams': 150},
            {'meal_name': 'Acompanhamento Café',        'meal_time': '07:30', 'product_id': 5,  'qty_grams': 70},
            {'meal_name': 'Shake Pós-Treino',           'meal_time': '10:00', 'product_id': 1,  'qty_grams': 40},
            {'meal_name': 'Almoço (Peito de Frango)',   'meal_time': '13:00', 'product_id': 4,  'qty_grams': 180},
            {'meal_name': 'Carboidrato Almoço',         'meal_time': '13:00', 'product_id': 13, 'qty_grams': 220},
            {'meal_name': 'Lanche da Tarde',            'meal_time': '16:30', 'product_id': 7,  'qty_grams': 200},
            {'meal_name': 'Gorduras Boas Tarde',        'meal_time': '16:30', 'product_id': 6,  'qty_grams': 30},
            {'meal_name': 'Jantar (Salmão Fresco)',     'meal_time': '20:00', 'product_id': 12, 'qty_grams': 160},
            {'meal_name': 'Carboidrato Jantar',         'meal_time': '20:00', 'product_id': 8,  'qty_grams': 250},
        ]
    elif 'low' in goal or 'cetog' in goal:
        base_meals = [
            {'meal_name': 'Café da Manhã (Ovos)',       'meal_time': '08:00', 'product_id': 9,  'qty_grams': 160},
            {'meal_name': 'Gorduras Café',              'meal_time': '08:00', 'product_id': 6,  'qty_grams': 30},
            {'meal_name': 'Almoço (Salmão Fresco)',     'meal_time': '12:30', 'product_id': 12, 'qty_grams': 200},
            {'meal_name': 'Vegetais Almoço',            'meal_time': '12:30', 'product_id': 10, 'qty_grams': 200},
            {'meal_name': 'Lanche (Whey Isolado)',      'meal_time': '16:30', 'product_id': 1,  'qty_grams': 35},
            {'meal_name': 'Mix Castanhas Tarde',        'meal_time': '16:30', 'product_id': 14, 'qty_grams': 40},
            {'meal_name': 'Jantar (Peito de Frango)',   'meal_time': '20:00', 'product_id': 4,  'qty_grams': 180},
            {'meal_name': 'Gorduras Jantar',            'meal_time': '20:00', 'product_id': 6,  'qty_grams': 30},
        ]
    elif 'plant' in goal or 'veg' in goal or 3 in restrictions:
        base_meals = [
            {'meal_name': 'Café (Leite de Amêndoas)',   'meal_time': '07:30', 'product_id': 3,  'qty_grams': 250},
            {'meal_name': 'Aveia S/ Glúten',            'meal_time': '07:30', 'product_id': 5,  'qty_grams': 75},
            {'meal_name': 'Fruta Café (Banana)',        'meal_time': '07:30', 'product_id': 15, 'qty_grams': 120},
            {'meal_name': 'Almoço (Tofu Firme)',        'meal_time': '12:30', 'product_id': 11, 'qty_grams': 220},
            {'meal_name': 'Carboidrato Almoço',         'meal_time': '12:30', 'product_id': 13, 'qty_grams': 250},
            {'meal_name': 'Vegetais Almoço',            'meal_time': '12:30', 'product_id': 10, 'qty_grams': 150},
            {'meal_name': 'Lanche da Tarde',            'meal_time': '16:00', 'product_id': 6,  'qty_grams': 30},
            {'meal_name': 'Castanhas Tarde',            'meal_time': '16:00', 'product_id': 14, 'qty_grams': 30},
            {'meal_name': 'Jantar (Tofu Orgânico)',     'meal_time': '19:30', 'product_id': 11, 'qty_grams': 180},
            {'meal_name': 'Carboidrato Jantar',         'meal_time': '19:30', 'product_id': 8,  'qty_grams': 240},
        ]
    else: # Déficit / Emagrecimento padrão
        base_meals = [
            {'meal_name': 'Café da Manhã (Ovos)',       'meal_time': '08:00', 'product_id': 9,  'qty_grams': 100},
            {'meal_name': 'Acompanhamento Café',        'meal_time': '08:00', 'product_id': 5,  'qty_grams': 45},
            {'meal_name': 'Almoço (Peito de Frango)',   'meal_time': '12:30', 'product_id': 4,  'qty_grams': 160},
            {'meal_name': 'Carboidrato Almoço',         'meal_time': '12:30', 'product_id': 13, 'qty_grams': 150},
            {'meal_name': 'Vegetais Almoço',            'meal_time': '12:30', 'product_id': 10, 'qty_grams': 150},
            {'meal_name': 'Lanche da Tarde',            'meal_time': '16:00', 'product_id': 7,  'qty_grams': 180},
            {'meal_name': 'Castanhas Tarde',            'meal_time': '16:00', 'product_id': 14, 'qty_grams': 20},
            {'meal_name': 'Jantar (Salmão)',            'meal_time': '19:30', 'product_id': 12, 'qty_grams': 140},
            {'meal_name': 'Carboidrato Jantar',         'meal_time': '19:30', 'product_id': 8,  'qty_grams': 160},
        ]

    # Ajuste proporcional de gramas para bater o target_kcal solicitado
    initial_kcal = 0
    for m in base_meals:
        prod = prod_map.get(m['product_id'])
        if prod and prod['nutritional_info']:
            info = json.loads(prod['nutritional_info']) if isinstance(prod['nutritional_info'], str) else prod['nutritional_info']
            initial_kcal += (info.get('kcal', 0) * m['qty_grams'] / 100.0)

    if initial_kcal > 0:
        ratio = target_kcal / initial_kcal
        for m in base_meals:
            m['qty_grams'] = max(10, int(round(m['qty_grams'] * ratio / 5.0) * 5))

    return jsonify({'status': 'success', 'meals': base_meals})


@app.route('/api/nutritionist/diet/save', methods=['POST'])
def save_prescribed_diet():
    """Prescreve ou atualiza a dieta de um paciente em tempo real."""
    data = request.json or {}
    patient_id = data.get('patient_id')
    nutri_id = data.get('nutritionist_id', 3)
    title = data.get('title', 'Novo Plano Alimentar')
    target_kcal = int(data.get('target_kcal', 2000))
    target_protein = int(data.get('target_protein', 150))
    target_carbs = int(data.get('target_carbs', 200))
    target_fat = int(data.get('target_fat', 60))
    notes = data.get('notes', '')
    goal = data.get('goal', 'Hipertrofia Muscular')
    restrictions = data.get('restriction_tag_ids', []) # List of tag IDs
    meals = data.get('meals', []) # List of { meal_name, meal_time, recommended_product_id, qty_grams }

    if not patient_id:
        return jsonify({'status': 'error', 'message': 'Paciente não especificado'}), 400

    db = get_db()
    db.row_factory = dict_factory

    # 1. Desativa dietas anteriores do paciente
    db.execute("UPDATE diets SET is_active = 0 WHERE patient_id = ?", (patient_id,))

    # 2. Cria nova dieta ativa
    cursor = db.execute('''
        INSERT INTO diets (patient_id, nutritionist_id, title, target_kcal, target_protein, target_carbs, target_fat, notes, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    ''', (patient_id, nutri_id, title, target_kcal, target_protein, target_carbs, target_fat, notes))
    new_diet_id = cursor.lastrowid

    # 3. Insere refeições
    for idx, m in enumerate(meals, 1):
        pid = m.get('recommended_product_id')
        cat = 'Geral'
        if pid:
            prod = db.execute("SELECT category FROM products WHERE id = ?", (pid,)).fetchone()
            if prod:
                cat = prod['category'] if isinstance(prod, dict) else prod[0]

        db.execute('''
            INSERT INTO diet_items (diet_id, meal_name, meal_time, meal_order, product_category, recommended_product_id, qty_grams)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (new_diet_id, m.get('meal_name', f'Refeição {idx}'), m.get('meal_time', '12:00'), idx, cat, pid, int(m.get('qty_grams', 100))))

    # 4. Atualiza restrições do paciente
    db.execute("DELETE FROM user_restrictions WHERE user_id = ?", (patient_id,))
    for tid in restrictions:
        try:
            db.execute("INSERT OR IGNORE INTO user_restrictions (user_id, tag_id) VALUES (?, ?)", (patient_id, int(tid)))
        except Exception:
            pass

    # 5. Atualiza o objetivo do perfil
    db.execute("UPDATE user_profiles SET goal = ? WHERE user_id = ?", (goal, patient_id))

    db.commit()
    return jsonify({
        'status': 'success',
        'message': 'Dieta clínica prescrita e sincronizada com sucesso!',
        'diet_id': new_diet_id
    })


# ==============================================================================
# LOCATION & REAL GEOCODING HELPERS
# ==============================================================================
KNOWN_REGIONAL_COORDS = {
    "045": (-23.5855, -46.6784, "Itaim Bibi / Vila Olímpia", "SP"),
    "054": (-23.5670, -46.6890, "Pinheiros", "SP"),
    "040": (-23.6030, -46.6630, "Moema / Vila Mariana", "SP"),
    "014": (-23.5605, -46.6660, "Jardins / Cerqueira César", "SP"),
    "013": (-23.5610, -46.6560, "Bela Vista / Paulista", "SP"),
    "050": (-23.5320, -46.6880, "Perdizes / Pompeia", "SP"),
    "031": (-23.5645, -46.5988, "Mooca", "SP"),
    "033": (-23.5395, -46.5682, "Tatuapé", "SP"),
    "041": (-23.6120, -46.6380, "Saúde / Vila Clementino", "SP"),
}

def haversine_km(lat1, lon1, lat2, lon2):
    """Calcula a distância em quilômetros entre duas coordenadas GPS."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

def resolve_location(lat=None, lng=None, cep=None, address_query=None):
    """
    Resolve o endereço detalhado e coordenadas geográficas com base em GPS, CEP ou busca de texto.
    """
    res = {
        'lat': -23.5855,
        'lng': -46.6784,
        'cep': '04538-133',
        'address': 'Rua Tabapuã, 1123 - Itaim Bibi, São Paulo - SP',
        'neighborhood': 'Itaim Bibi',
        'city': 'São Paulo',
        'state': 'SP',
        'source': 'default'
    }

    # 1. Se recebemos coordenadas GPS precisas (do navegador)
    if lat is not None and lng is not None:
        try:
            f_lat = float(lat)
            f_lng = float(lng)
            req = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/reverse?format=json&lat={f_lat}&lon={f_lng}&addressdetails=1",
                headers={'User-Agent': 'SmartDiet/1.0 (contact@smartdiet.com)'}
            )
            with urllib.request.urlopen(req, timeout=3.5) as response:
                geo_data = json.loads(response.read().decode())
                addr_info = geo_data.get('address', {})
                road = addr_info.get('road') or addr_info.get('pedestrian') or addr_info.get('street') or ''
                num = addr_info.get('house_number') or ''
                suburb = addr_info.get('suburb') or addr_info.get('neighbourhood') or addr_info.get('quarter') or 'São Paulo'
                city = addr_info.get('city') or addr_info.get('town') or addr_info.get('municipality') or 'São Paulo'
                state = addr_info.get('state_code') or addr_info.get('state') or 'SP'
                postcode = addr_info.get('postcode') or res['cep']
                
                street_num = f"{road}, {num}".strip(', ') if road else suburb
                formatted = f"{street_num} - {suburb}, {city} - {state}"
                
                return {
                    'lat': f_lat,
                    'lng': f_lng,
                    'cep': postcode,
                    'address': formatted,
                    'neighborhood': suburb,
                    'city': city,
                    'state': state,
                    'source': 'gps'
                }
        except Exception as e:
            logger.warning(f"Erro no reverse geocoding do GPS: {e}")
            res['lat'] = float(lat)
            res['lng'] = float(lng)
            res['source'] = 'gps_coords_only'

    # 2. Se temos CEP informado
    if cep:
        cep_clean = str(cep).replace('-', '').replace('.', '').strip()
        if len(cep_clean) >= 5:
            prefix = cep_clean[:3]
            if prefix in KNOWN_REGIONAL_COORDS:
                reg_lat, reg_lng, reg_bairro, reg_uf = KNOWN_REGIONAL_COORDS[prefix]
                res['lat'] = reg_lat
                res['lng'] = reg_lng
                res['neighborhood'] = reg_bairro
                res['cep'] = f"{cep_clean[:5]}-{cep_clean[5:]}" if len(cep_clean) == 8 else cep_clean
                res['address'] = f"{reg_bairro}, São Paulo - {reg_uf}"
                res['source'] = 'cep_cached'

            try:
                req = urllib.request.Request(f"https://viacep.com.br/ws/{cep_clean}/json/", headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=3.0) as response:
                    viacep_data = json.loads(response.read().decode())
                    if 'erro' not in viacep_data:
                        logradouro = viacep_data.get('logradouro') or ''
                        bairro = viacep_data.get('bairro') or res['neighborhood']
                        cidade = viacep_data.get('localidade') or 'São Paulo'
                        uf = viacep_data.get('uf') or 'SP'
                        cep_fmt = viacep_data.get('cep') or cep
                        
                        street_part = logradouro if logradouro else bairro
                        formatted = f"{street_part} - {bairro}, {cidade} - {uf}".strip(' - ')
                        
                        res['cep'] = cep_fmt
                        res['address'] = formatted
                        res['neighborhood'] = bairro
                        res['city'] = cidade
                        res['state'] = uf
                        res['source'] = 'viacep'
            except Exception as e:
                logger.warning(f"Erro no ViaCEP: {e}")

    # 3. Se temos busca por endereço de texto
    if address_query and (not lat or not lng):
        try:
            encoded_query = urllib.parse.quote(address_query)
            req = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/search?format=json&q={encoded_query}&limit=1&addressdetails=1",
                headers={'User-Agent': 'SmartDiet/1.0 (contact@smartdiet.com)'}
            )
            with urllib.request.urlopen(req, timeout=3.5) as response:
                search_data = json.loads(response.read().decode())
                if search_data and len(search_data) > 0:
                    first = search_data[0]
                    res['lat'] = float(first['lat'])
                    res['lng'] = float(first['lon'])
                    res['address'] = first.get('display_name', address_query)
                    res['source'] = 'address_search'
        except Exception as e:
            logger.warning(f"Erro na busca de endereço nominatim: {e}")

    return res


@app.route('/api/location/resolve', methods=['POST', 'GET'])
def api_resolve_location():
    """Endpoint para resolver localização em tempo real via GPS ou CEP."""
    if request.method == 'POST':
        data = request.json or {}
        lat = data.get('lat')
        lng = data.get('lng')
        cep = data.get('cep')
        address_query = data.get('address')
    else:
        lat = request.args.get('lat')
        lng = request.args.get('lng')
        cep = request.args.get('cep')
        address_query = request.args.get('address')

    loc = resolve_location(lat=lat, lng=lng, cep=cep, address_query=address_query)
    return jsonify({
        'status': 'success',
        'location': loc
    })


# ==============================================================================
# CORE ALGORITHM — MATCHING DE ESTOQUE POR ENDEREÇO
# ==============================================================================
def fetch_gpa_delivery_stores_for_cep(cep):
    """Descobre filiais GPA que atendem diretamente o CEP do consumidor."""
    cep_limpo = str(cep).replace("-", "").replace(".", "").strip()
    url = f"https://api.vendas.gpa.digital/pa/delivery-v2/ecom/deliveryOptions?zipCode={cep_limpo}"
    stores = []
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode())
            options = data.get('deliveryTypes', [])
            seen_ids = set()
            for op in options:
                sid = op.get('storeid')
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    sname = op.get('storeName') or 'Pão de Açúcar'
                    stype = op.get('storeType') or ''
                    brand = 'Minuto Pão de Açúcar' if 'minuto' in sname.lower() or 'minuto' in stype.lower() else 'Pão de Açúcar'
                    addr = op.get('address', {})
                    street = addr.get('street') or ''
                    num = addr.get('addressNumber') or ''
                    neigh = addr.get('neighborhood') or ''
                    city = addr.get('city') or 'São Paulo'
                    full_addr = f"{street}, {num} - {neigh}, {city}".strip(', -')
                    
                    stores.append({
                        'gpa_store_id': sid,
                        'brand_name': brand,
                        'branch_name': sname,
                        'address': full_addr,
                        'is_direct_delivery': True,
                        'delivery_mode': op.get('deliveryType', 'Express')
                    })
    except Exception as e:
        logger.debug(f"GPA delivery options skip/fallback: {e}")
    return stores


def generate_dynamic_inventory_for_market(market_id, db):
    db.row_factory = dict_factory
    products = db.execute("SELECT * FROM products WHERE is_active = 1").fetchall()
    
    dynamic_inventory = []
    import random
    random.seed(int(datetime.now().strftime('%Y%m%d%H')) + market_id)
    for p in products:
        has_stock = random.random() > 0.12 # 88% chance of stock
        if has_stock:
            stock_qty = random.randint(8, 65)
            markup = 1.0 + (random.random() * 0.16 - 0.08)
            current_price = round(p['base_price'] * markup, 2)
            dynamic_inventory.append({
                'product_id': p['id'],
                'name': p['name'],
                'category': p['category'],
                'image_url': p['image_url'],
                'stock_qty': stock_qty,
                'current_price': current_price
            })
    return dynamic_inventory

@app.route('/api/market/dynamic_inventory', methods=['GET'])
def get_dynamic_inventory():
    """Endpoint que simula uma API externa de supermercado gerando dados dinamicamente."""
    market_id = int(request.args.get('market_id', 1))
    db = get_db()
    dynamic_inventory = generate_dynamic_inventory_for_market(market_id, db)
    return jsonify({'status': 'success', 'data': dynamic_inventory})

@app.route('/api/core/algorithm/match', methods=['POST'])
def optimize_smart_cart():
    """
    ALGORITMO PRINCIPAL DA PLATAFORMA.
    Cruza produtos da dieta com estoques de supermercados específicos para a localização/endereço do usuário.
    """
    data = request.json or {}
    product_ids = data.get('product_ids', [])
    cep = data.get('cep', None)
    lat = data.get('lat', None)
    lng = data.get('lng', None)
    address_query = data.get('address', None)

    # 1. Resolve localização precisa do usuário
    user_loc = resolve_location(lat=lat, lng=lng, cep=cep, address_query=address_query)
    user_lat = user_loc['lat']
    user_lng = user_loc['lng']
    resolved_cep = user_loc['cep']

    logger.info(f"Executando match para {len(product_ids)} itens no endereço: {user_loc['address']} (Lat: {user_lat}, Lng: {user_lng})")

    if not product_ids:
        logger.warning("Lista de produtos vazia no algoritmo de match.")
        return jsonify({'status': 'error', 'message': 'Lista de produtos vazia'}), 400

    db = get_db()
    db.row_factory = dict_factory
    
    # 2. Busca mercados cadastrados no banco de dados
    db_markets = db.execute("SELECT * FROM markets WHERE is_active = 1").fetchall()
    
    # 3. Tenta buscar filiais de entrega direta via GPA para o CEP
    gpa_stores = fetch_gpa_delivery_stores_for_cep(resolved_cep) if resolved_cep else []

    all_target_markets = []
    
    # Se encontramos lojas com entrega direta para o CEP
    for gstore in gpa_stores[:3]:
        # Encontra coordenadas próximas no banco ou estima
        m_lat = user_lat + (0.004 * (len(all_target_markets) + 1))
        m_lng = user_lng + (0.003 * (len(all_target_markets) + 1))
        all_target_markets.append({
            'id': 100 + len(all_target_markets),
            'brand_name': gstore['brand_name'],
            'branch_name': gstore['branch_name'],
            'address': gstore['address'],
            'lat': m_lat,
            'lng': m_lng,
            'is_direct_delivery': True,
            'delivery_type': gstore['delivery_mode']
        })

    # Adiciona lojas do banco de dados físico de SP
    for m in db_markets:
        all_target_markets.append({
            'id': m['id'],
            'brand_name': m['brand_name'],
            'branch_name': m['branch_name'],
            'address': m['address'] or 'São Paulo - SP',
            'lat': m['lat'] if m['lat'] is not None else user_lat + 0.008,
            'lng': m['lng'] if m['lng'] is not None else user_lng + 0.008,
            'is_direct_delivery': False,
            'delivery_type': 'Entrega Padrão'
        })

    results = []

    for m in all_target_markets:
        market_id = m['id']
        total_cart_price = 0.0
        found_items = 0
        missing_items = []
        found_details = []

        try:
            ext_inventory = generate_dynamic_inventory_for_market(market_id, db)
        except Exception as e:
            logger.error(f"Erro gerando inventário para mercado {market_id}: {e}")
            ext_inventory = []

        inv_map = { item['product_id']: item for item in ext_inventory }

        for pid in product_ids:
            inv = inv_map.get(pid)
            if inv and inv['stock_qty'] > 0:
                found_items += 1
                total_cart_price += inv['current_price']
                found_details.append({
                    'product_id': pid,
                    'name': inv['name'],
                    'category': inv['category'],
                    'price': round(inv['current_price'], 2),
                    'qty_available': inv['stock_qty'],
                    'image_url': inv['image_url'],
                    'status': 'available'
                })
            else:
                prod = db.execute("SELECT id, name, category, base_price, image_url FROM products WHERE id = ?", (pid,)).fetchone()
                if prod:
                    missing_items.append({'product_id': pid, 'name': prod['name']})
                    found_details.append({
                        'product_id': pid,
                        'name': prod['name'],
                        'category': prod['category'],
                        'price': round(prod['base_price'], 2),
                        'qty_available': 0,
                        'image_url': prod['image_url'],
                        'status': 'out_of_stock'
                    })

        match_percentage = int((found_items / len(product_ids)) * 100) if product_ids else 0
        m_lat = m['lat']
        m_lng = m['lng']
        dist_km = haversine_km(user_lat, user_lng, m_lat, m_lng)
        
        # Tempo estimado de entrega: ~4 min base + 3.2 min por km
        travel_time_min = max(6, int(dist_km * 3.2 + 4))

        results.append({
            'market_id': market_id,
            'brand': m['brand_name'],
            'branch': m['branch_name'],
            'address': m['address'],
            'lat': m_lat,
            'lng': m_lng,
            'distance_km': dist_km,
            'travel_time_min': travel_time_min,
            'match_score': match_percentage,
            'total_price': round(total_cart_price, 2),
            'items_found': found_items,
            'items_missing': missing_items,
            'cart_details': found_details,
            'is_direct_delivery': m.get('is_direct_delivery', False),
            'delivery_type': m.get('delivery_type', 'Express')
        })

    # Ordena por melhor compatibilidade de itens, menor distância e menor preço
    results.sort(key=lambda x: (-x['match_score'], x['distance_km'], x['total_price']))
    
    # Limita às 6 melhores opções
    results = results[:6]

    logger.info(f"Match concluído com sucesso para {user_loc['address']}! Melhor mercado: {results[0]['brand']} ({results[0]['branch']}) a {results[0]['distance_km']} km.")

    return jsonify({
        'status': 'success',
        'user_location': user_loc,
        'delivery_address': user_loc['address'],
        'analyzed_markets': len(results),
        'routes': results
    })


# ==============================================================================
# MARKET (B2B) ENDPOINTS
# ==============================================================================
@app.route('/api/market/analytics', methods=['GET'])
def get_market_analytics():
    market_id = int(request.args.get('market_id', 1))
    db = get_db()
    db.row_factory = dict_factory

    missed = db.execute('''
        SELECT p.name, p.category,
               ROUND(p.base_price * m.markup_multiplier * (ABS(RANDOM() % 50) + 15), 2) as estimated_loss,
               ABS(RANDOM() % 120 + 25) as search_volume
        FROM products p
        JOIN markets m ON m.id = ?
        LEFT JOIN inventory i ON p.id = i.product_id AND i.market_id = m.id
        WHERE (i.stock_qty IS NULL OR i.stock_qty = 0)
        LIMIT 6
    ''', (market_id,)).fetchall()

    kpi_base = {1: (1245, 214.50, '18.5%'), 2: (892, 187.30, '14.2%'), 3: (1087, 205.00, '16.8%'), 4: (2103, 178.90, '22.1%')}
    kpis = kpi_base.get(market_id, (1000, 200.00, '15.0%'))

    return jsonify({
        'status': 'success',
        'kpis': {
            'routed_users_month': kpis[0],
            'avg_ticket': kpis[1],
            'conversion_rate': kpis[2]
        },
        'missed_opportunities': missed
    })


@app.route('/api/market/inventory', methods=['GET'])
def get_market_inventory():
    market_id = int(request.args.get('market_id', 1))
    db = get_db()
    try:
        ext_inventory = generate_dynamic_inventory_for_market(market_id, db)
    except Exception:
        ext_inventory = []

    # Map to expected format
    items = []
    for item in ext_inventory:
        items.append({
            'product_id': item['product_id'],
            'name': item['name'],
            'brand': 'Marca', # Simplified
            'category': item['category'],
            'sku': f"SKU00{item['product_id']}",
            'image_url': item['image_url'],
            'base_price': item['current_price'],
            'stock_qty': item['stock_qty'],
            'current_price': item['current_price'],
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    return jsonify({'status': 'success', 'data': items})


@app.route('/api/market/inventory/update', methods=['PUT'])
def update_inventory():
    data = request.json
    market_id = data.get('market_id', 1)
    product_id = data.get('product_id')
    stock_qty = data.get('stock_qty', 0)
    current_price = data.get('current_price')

    db = get_db()
    existing = db.execute(
        "SELECT 1 FROM inventory WHERE market_id = ? AND product_id = ?",
        (market_id, product_id)
    ).fetchone()

    if existing:
        db.execute('''
            UPDATE inventory
            SET stock_qty = ?, current_price = ?, last_updated = CURRENT_TIMESTAMP
            WHERE market_id = ? AND product_id = ?
        ''', (stock_qty, current_price, market_id, product_id))
    else:
        db.execute(
            "INSERT INTO inventory (market_id, product_id, stock_qty, current_price) VALUES (?, ?, ?, ?)",
            (market_id, product_id, stock_qty, current_price)
        )

    db.commit()
    return jsonify({'status': 'success', 'message': 'Estoque atualizado com sucesso.'})


@app.route('/api/products/search', methods=['GET'])
def search_products():
    query = request.args.get('q', '')
    category = request.args.get('category', '')
    db = get_db()
    db.row_factory = dict_factory

    sql = "SELECT id, sku, name, brand, category, nutritional_info, base_price, image_url FROM products WHERE is_active = 1"
    params = []

    if query:
        sql += " AND (name LIKE ? OR brand LIKE ? OR category LIKE ?)"
        q = f"%{query}%"
        params.extend([q, q, q])

    if category:
        sql += " AND category = ?"
        params.append(category)

    sql += " ORDER BY category, name"
    prods = db.execute(sql, params).fetchall()

    for p in prods:
        p['nutritional_info'] = json.loads(p['nutritional_info']) if p['nutritional_info'] else {}

    return jsonify({'status': 'success', 'data': prods})


if __name__ == '__main__':
    print("=" * 60)
    print("  SmartDiet Enterprise Backend v3.0 - Multilateral")
    print("=" * 60)
    init_db()
    print("  [OK] Banco de dados e schema inicializados com sucesso!")
    print("  [OK] Servidor ativo em: http://localhost:5000")
    print("  >> Consumidor:    paciente@demo.com  / 123456")
    print("  >> Nutricionista: sarah@nutri.com    / 123456")
    print("  >> Varejo B2B:    gestor@pda.com     / 123456")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)