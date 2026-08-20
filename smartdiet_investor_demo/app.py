import os
import sqlite3
import json
import math
from datetime import datetime, date
from flask import Flask, request, jsonify, g, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder='static')
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'smartdiet_production.db')

@app.route('/')
def serve_index():
    return send_from_directory('static', 'index.html')

# ==============================================================================
# BANCO DE DADOS
# ==============================================================================
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
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
    cursor.executemany("INSERT INTO user_profiles (user_id, lat, lng, weight_kg, height_cm, goal, nutritionist_id, avatar_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (2, -23.585, -46.678, 82.0, 180.0, 'Hipertrofia Muscular', 3, 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=200&q=80'),
        (3, -23.585, -46.678, 62.0, 168.0, 'Nutrição Clínica & Esportiva', None, 'https://images.unsplash.com/photo-1559839734-2b71ea197ec2?auto=format&fit=crop&w=200&q=80'),
        (4, -23.585, -46.678, 75.0, 175.0, 'Gestão de Vendas', None, 'https://images.unsplash.com/photo-1560250097-0b93528c311a?auto=format&fit=crop&w=200&q=80'),
        (6, -23.570, -46.660, 58.0, 164.0, 'Emagrecimento & Definição', 3, 'https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&w=200&q=80'),
        (7, -23.590, -46.670, 88.0, 185.0, 'Performance & Low Carb', 3, 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=200&q=80'),
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

    # Catálogo de Produtos Expandido
    prods = [
        (1, 'SKU001', '78910001', 'Whey Protein Isolado Dux 900g',    'Dux',         'Suplementos',        json.dumps({'kcal': 120, 'prot': 24, 'carb': 2,   'fat': 1}),   199.90, 'https://images.unsplash.com/photo-1593095948071-474c5cc2989d?auto=format&fit=crop&w=200&q=80'),
        (2, 'SKU002', '78910002', 'Pão de Forma S/ Glúten Schar',     'Schar',       'Padaria',            json.dumps({'kcal': 180, 'prot': 3,  'carb': 35,  'fat': 4}),    24.50, 'https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=200&q=80'),
        (3, 'SKU003', '78910003', 'Leite de Amêndoas Silk 1L',        'Silk',        'Laticínios Veganos',  json.dumps({'kcal': 40,  'prot': 1,  'carb': 2,   'fat': 3}),    19.90, 'https://images.unsplash.com/photo-1550583724-b2692b85b150?auto=format&fit=crop&w=200&q=80'),
        (4, 'SKU004', '78910004', 'Peito de Frango Resfriado 1kg',    'Seara',       'Carnes',             json.dumps({'kcal': 110, 'prot': 23, 'carb': 0,   'fat': 2}),    22.90, 'https://images.unsplash.com/photo-1604503468506-a8da13d11d36?auto=format&fit=crop&w=200&q=80'),
        (5, 'SKU005', '78910005', 'Aveia em Flocos S/ Glúten 500g',   'Quaker',      'Cereais',            json.dumps({'kcal': 150, 'prot': 5,  'carb': 27,  'fat': 3}),    14.90, 'https://images.unsplash.com/photo-1495214783159-3503fd1b572d?auto=format&fit=crop&w=200&q=80'),
        (6, 'SKU006', '78910006', 'Pasta de Amendoim Integral 500g',  'Power1',      'Lanches',            json.dumps({'kcal': 190, 'prot': 8,  'carb': 6,   'fat': 16}),   18.00, 'https://images.unsplash.com/photo-1608571423902-eed4a5ad8108?auto=format&fit=crop&w=200&q=80'),
        (7, 'SKU007', '78910007', 'Iogurte Proteico Zero Lactose',    'Verde Campo', 'Laticínios',        json.dumps({'kcal': 90,  'prot': 14, 'carb': 8,   'fat': 0}),     7.50, 'https://images.unsplash.com/photo-1488477181946-6428a0291777?auto=format&fit=crop&w=200&q=80'),
        (8, 'SKU008', '78910008', 'Batata Doce Branca 1kg',           'Hortifruti',  'Vegetais',           json.dumps({'kcal': 86,  'prot': 1.6,'carb': 20,  'fat': 0.1}),    5.90, 'https://images.unsplash.com/photo-1596097635232-7ba7c9fe92fe?auto=format&fit=crop&w=200&q=80'),
        (9, 'SKU009', '78910009', 'Ovos Caipiras Orgânicos 12un',     'Sítio Bom',   'Proteínas',         json.dumps({'kcal': 70,  'prot': 6,  'carb': 0,   'fat': 5}),    16.90, 'https://images.unsplash.com/photo-1506976785307-8732e854ad03?auto=format&fit=crop&w=200&q=80'),
        (10,'SKU010', '78910010', 'Brócolis Orgânico 500g',           'Hortifruti',  'Vegetais',           json.dumps({'kcal': 34,  'prot': 2.8,'carb': 7,   'fat': 0.4}),    9.90, 'https://images.unsplash.com/photo-1459411621453-7b03977f4bfc?auto=format&fit=crop&w=200&q=80'),
        (11,'SKU011', '78910011', 'Tofu Orgânico Firme 400g',         'Agronature',  'Laticínios Veganos',  json.dumps({'kcal': 76,  'prot': 8,  'carb': 1.9, 'fat': 4.8}),   17.90, 'https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=200&q=80'),
        (12,'SKU012', '78910012', 'Filé de Salmão Fresco 500g',       'Costa Sul',   'Carnes',             json.dumps({'kcal': 208, 'prot': 20, 'carb': 0,   'fat': 13}),   48.90, 'https://images.unsplash.com/photo-1467003909585-2f8a72700288?auto=format&fit=crop&w=200&q=80'),
        (13,'SKU013', '78910013', 'Arroz Integral Cateto 1kg',        'Camil',       'Cereais',            json.dumps({'kcal': 130, 'prot': 2.6,'carb': 28,  'fat': 1}),      8.50, 'https://images.unsplash.com/photo-1586201375761-83865001e31c?auto=format&fit=crop&w=200&q=80'),
        (14,'SKU014', '78910014', 'Mix de Castanhas Nobres 200g',     'Mundo Verde', 'Lanches',            json.dumps({'kcal': 185, 'prot': 5,  'carb': 5,   'fat': 17}),   22.90, 'https://images.unsplash.com/photo-1509722747041-616f39b57569?auto=format&fit=crop&w=200&q=80'),
        (15,'SKU015', '78910015', 'Creatina Monohidratada 300g',      'Creapure',    'Suplementos',        json.dumps({'kcal': 0,   'prot': 0,  'carb': 0,   'fat': 0}),     99.00, 'https://images.unsplash.com/photo-1579722821273-0f6c7d44362f?auto=format&fit=crop&w=200&q=80'),
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
        (15,1),(15,2),(15,3),(15,4),(15,6);
    ''')

    # Mercados
    cursor.executemany("INSERT INTO markets (id, owner_id, brand_name, branch_name, address, lat, lng, markup_multiplier) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, 4, 'Pão de Açúcar', 'Faria Lima',    'Av. Brig. Faria Lima, 3500', -23.585, -46.678, 1.15),
        (2, 5, 'Mundo Verde',   'Pinheiros',     'R. dos Pinheiros, 1000',     -23.567, -46.699, 1.25),
        (3, 4, 'Pão de Açúcar', 'Moema',         'Av. Ibirapuera, 3103',       -23.600, -46.660, 1.10),
        (4, 5, 'Carrefour',     'Itaim',         'R. João Cachoeira, 300',     -23.580, -46.680, 0.95),
    ])

    # Inventário distribuído
    for pid in range(1, 16):
        cursor.execute("INSERT INTO inventory (market_id, product_id, stock_qty, current_price) VALUES (1, ?, ?, (SELECT base_price * 1.15 FROM products WHERE id = ?))", (pid, 50, pid))
    for pid in [1, 2, 3, 5, 6, 7, 10, 11, 13, 14, 15]:
        cursor.execute("INSERT INTO inventory (market_id, product_id, stock_qty, current_price) VALUES (2, ?, ?, (SELECT base_price * 1.25 FROM products WHERE id = ?))", (pid, 35, pid))
    for pid in [3, 4, 5, 6, 7, 8, 9, 10, 12, 13]:
        cursor.execute("INSERT INTO inventory (market_id, product_id, stock_qty, current_price) VALUES (4, ?, ?, (SELECT base_price * 0.95 FROM products WHERE id = ?))", (pid, 90, pid))

    # Dieta ativa de André Suhai (Paciente 2)
    cursor.execute("""
        INSERT INTO diets (id, patient_id, nutritionist_id, title, target_kcal, target_protein, target_carbs, target_fat, notes)
        VALUES (1, 2, 3, 'Plano Hipertrofia — Fase Bulking Limpo', 2150, 160, 220, 65,
        'Foco em ganho de massa magra com controle de lactose e glúten. Aumentar ingestão hídrica para 3.5L/dia.')
    """)

    cursor.executemany("""
        INSERT INTO diet_items (diet_id, meal_name, meal_time, meal_order, product_category, recommended_product_id, qty_grams)
        VALUES (1, ?, ?, ?, ?, ?, ?)
    """, [
        ('Café da Manhã',   '07:30', 1, 'Cereais',     5,  60),
        ('Shake Pré-Treino', '10:00', 2, 'Suplementos', 1,  40),
        ('Almoço',          '13:00', 3, 'Carnes',      4, 150),
        ('Lanche da Tarde', '16:30', 4, 'Laticínios',  7, 200),
        ('Jantar',          '20:00', 5, 'Vegetais',   10, 300),
    ])

    # Dieta de Camila Torres (Paciente 6)
    cursor.execute("""
        INSERT INTO diets (id, patient_id, nutritionist_id, title, target_kcal, target_protein, target_carbs, target_fat, notes)
        VALUES (2, 6, 3, 'Protocolo Plant-Based & Definição', 1650, 110, 180, 45,
        'Dieta 100% vegana, foco em saciedade e perfil glicêmico estável.')
    """)
    cursor.executemany("""
        INSERT INTO diet_items (diet_id, meal_name, meal_time, meal_order, product_category, recommended_product_id, qty_grams)
        VALUES (2, ?, ?, ?, ?, ?, ?)
    """, [
        ('Café da Manhã', '08:00', 1, 'Laticínios Veganos', 3,  250),
        ('Almoço',        '12:30', 2, 'Laticínios Veganos', 11, 200),
        ('Lanche',        '16:00', 3, 'Lanches',            14,  40),
        ('Jantar',        '19:30', 4, 'Vegetais',           10, 250),
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
    """Protocolos clínicos prontos para carregamento rápido."""
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
            'notes': 'Foco em superávit calórico controlado, alta biodisponibilidade de aminoácidos essenciais e digestibilidade ótima.',
            'meals': [
                {'meal_name': 'Café da Manhã',   'meal_time': '07:30', 'product_id': 5,  'qty_grams': 60},
                {'meal_name': 'Shake Pré-Treino', 'meal_time': '10:00', 'product_id': 1,  'qty_grams': 40},
                {'meal_name': 'Almoço',          'meal_time': '13:00', 'product_id': 4,  'qty_grams': 180},
                {'meal_name': 'Lanche da Tarde', 'meal_time': '16:30', 'product_id': 7,  'qty_grams': 200},
                {'meal_name': 'Jantar',          'meal_time': '20:00', 'product_id': 10, 'qty_grams': 300},
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
            'recommended_tags': [1, 6], # Zero Lactose, Zero Açúcar
            'notes': 'Déficit calórico com alta densidade de micronutrientes e fibras para saciedade prolongada.',
            'meals': [
                {'meal_name': 'Café da Manhã', 'meal_time': '08:00', 'product_id': 9,  'qty_grams': 120},
                {'meal_name': 'Almoço',        'meal_time': '12:30', 'product_id': 4,  'qty_grams': 150},
                {'meal_name': 'Lanche',        'meal_time': '16:00', 'product_id': 7,  'qty_grams': 150},
                {'meal_name': 'Jantar',        'meal_time': '19:30', 'product_id': 10, 'qty_grams': 250},
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
            'recommended_tags': [2, 5, 6], # Sem Glúten, Low Carb, Zero Açúcar
            'notes': 'Restrição severa de carboidratos refinados, aumento de gorduras boas e proteínas magras.',
            'meals': [
                {'meal_name': 'Café da Manhã', 'meal_time': '08:00', 'product_id': 9,  'qty_grams': 180},
                {'meal_name': 'Almoço',        'meal_time': '12:30', 'product_id': 12, 'qty_grams': 200},
                {'meal_name': 'Lanche',        'meal_time': '16:30', 'product_id': 6,  'qty_grams': 40},
                {'meal_name': 'Jantar',        'meal_time': '20:00', 'product_id': 10, 'qty_grams': 200},
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
            'recommended_tags': [3, 7], # Vegano, Orgânico
            'notes': 'Dieta baseada em plantas, rica em fitoquímicos, leguminosas e fontes integrais de energia.',
            'meals': [
                {'meal_name': 'Café da Manhã', 'meal_time': '07:30', 'product_id': 3,  'qty_grams': 250},
                {'meal_name': 'Almoço',        'meal_time': '12:30', 'product_id': 11, 'qty_grams': 220},
                {'meal_name': 'Lanche',        'meal_time': '16:00', 'product_id': 14, 'qty_grams': 40},
                {'meal_name': 'Jantar',        'meal_time': '19:30', 'product_id': 10, 'qty_grams': 300},
            ]
        }
    ]
    return jsonify({'status': 'success', 'protocols': protocols})


@app.route('/api/nutritionist/diet/save', methods=['POST'])
def save_prescribed_diet():
    """Prescreve ou atualiza a dieta de um paciente em tempo real."""
    data = request.json
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
        prod = db.execute("SELECT category FROM products WHERE id = ?", (pid,)).fetchone() if pid else None
        cat = prod['category'] if prod else 'Geral'
        db.execute('''
            INSERT INTO diet_items (diet_id, meal_name, meal_time, meal_order, product_category, recommended_product_id, qty_grams)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (new_diet_id, m.get('meal_name', f'Refeição {idx}'), m.get('meal_time', '12:00'), idx, cat, pid, int(m.get('qty_grams', 100))))

    # 4. Atualiza restrições do paciente
    db.execute("DELETE FROM user_restrictions WHERE user_id = ?", (patient_id,))
    for tid in restrictions:
        db.execute("INSERT OR IGNORE INTO user_restrictions (user_id, tag_id) VALUES (?, ?)", (patient_id, int(tid)))

    # 5. Atualiza o objetivo do perfil
    db.execute("UPDATE user_profiles SET goal = ? WHERE user_id = ?", (goal, patient_id))

    db.commit()
    return jsonify({
        'status': 'success',
        'message': 'Dieta clínica prescrita e sincronizada com sucesso!',
        'diet_id': new_diet_id
    })


# ==============================================================================
# CORE ALGORITHM — MATCHING DE ESTOQUE
# ==============================================================================
@app.route('/api/core/algorithm/match', methods=['POST'])
def optimize_smart_cart():
    """
    ALGORITMO PRINCIPAL DA PLATAFORMA.
    Cruza produtos da dieta com estoques dos supermercados próximos.
    """
    data = request.json
    product_ids = data.get('product_ids', [])
    user_lat = data.get('lat', -23.585)
    user_lng = data.get('lng', -46.678)

    if not product_ids:
        return jsonify({'status': 'error', 'message': 'Lista vazia'}), 400

    db = get_db()
    db.row_factory = dict_factory
    markets = db.execute("SELECT * FROM markets WHERE is_active = 1").fetchall()
    results = []

    for m in markets:
        market_id = m['id']
        total_cart_price = 0.0
        found_items = 0
        missing_items = []
        found_details = []

        for pid in product_ids:
            inv = db.execute('''
                SELECT i.stock_qty, i.current_price, p.name, p.image_url, p.category
                FROM inventory i
                JOIN products p ON i.product_id = p.id
                WHERE i.market_id = ? AND i.product_id = ?
            ''', (market_id, pid)).fetchone()

            if inv and inv['stock_qty'] > 0:
                found_items += 1
                total_cart_price += inv['current_price']
                found_details.append({
                    'product_id': pid,
                    'name': inv['name'],
                    'category': inv['category'],
                    'price': round(inv['current_price'], 2),
                    'qty_available': inv['stock_qty'],
                    'image_url': inv['image_url']
                })
            else:
                prod = db.execute("SELECT name FROM products WHERE id = ?", (pid,)).fetchone()
                if prod:
                    missing_items.append({'product_id': pid, 'name': prod['name']})

        match_percentage = int((found_items / len(product_ids)) * 100) if product_ids else 0
        dist_km = round(math.sqrt((m['lat'] - user_lat)**2 + (m['lng'] - user_lng)**2) * 111, 1)

        results.append({
            'market_id': market_id,
            'brand': m['brand_name'],
            'branch': m['branch_name'],
            'address': m['address'] or '',
            'distance_km': dist_km,
            'match_score': match_percentage,
            'total_price': round(total_cart_price, 2),
            'items_found': found_items,
            'items_missing': missing_items,
            'cart_details': found_details
        })

    results.sort(key=lambda x: (-x['match_score'], x['total_price'], x['distance_km']))

    return jsonify({
        'status': 'success',
        'analyzed_markets': len(markets),
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
    db.row_factory = dict_factory

    items = db.execute('''
        SELECT p.id as product_id, p.name, p.brand, p.category, p.sku, p.image_url,
               p.base_price,
               COALESCE(i.stock_qty, 0) as stock_qty,
               COALESCE(i.current_price, p.base_price) as current_price,
               i.last_updated
        FROM products p
        LEFT JOIN inventory i ON p.id = i.product_id AND i.market_id = ?
        WHERE p.is_active = 1
        ORDER BY p.category, p.name
    ''', (market_id,)).fetchall()

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