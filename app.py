from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
from datetime import datetime, date
import uuid
import base64

app = Flask(__name__, static_folder='static')
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB

DATA_FILE     = os.path.join(os.path.dirname(__file__), 'data', 'inquilinos.json')
MSGS_FILE     = os.path.join(os.path.dirname(__file__), 'data', 'mensagens.json')
CONTRATOS_DIR = os.path.join(os.path.dirname(__file__), 'data', 'contratos')

MSG_PADRAO_VENCIMENTO = """Olá, {nome}! 👋

Seu aluguel referente ao imóvel *{endereco}* vence *hoje*, dia {vencimento}.

💰 Valor: *R$ {valor}*
{pix_linha}

Qualquer dúvida, estou à disposição. Obrigado! 🏠"""

MSG_PADRAO_ATRASADO = """Olá, {nome}!

Verificamos que o aluguel do imóvel *{endereco}* está em aberto há *{dias_atraso} dia(s)*.

💰 Valor: *R$ {valor}*
📅 Vencimento: dia {vencimento}
{pix_linha}

Por favor, entre em contato para regularizar. Obrigado!"""

MSG_PADRAO_CONTRATO_60 = """⚠️ Contrato vencendo em breve

O contrato de *{nome}* ({endereco}) vence em *{dias_contrato} dias* ({data_fim}).

Lembre-se de tratar a renovação com antecedência."""

MSG_PADRAO_CONTRATO_30 = """🚨 Urgente — Contrato vence em 30 dias

O contrato de *{nome}* ({endereco}) vence em *{dias_contrato} dias* ({data_fim}) e ainda não foi renovado.

Providencie a renovação o quanto antes!"""

def ensure_data_dir():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    os.makedirs(CONTRATOS_DIR, exist_ok=True)

def load_inquilinos():
    ensure_data_dir()
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_inquilinos(data):
    ensure_data_dir()
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_mensagens():
    ensure_data_dir()
    base = {
        'vencimento':  MSG_PADRAO_VENCIMENTO,
        'atrasado':    MSG_PADRAO_ATRASADO,
        'contrato_60': MSG_PADRAO_CONTRATO_60,
        'contrato_30': MSG_PADRAO_CONTRATO_30,
    }
    if not os.path.exists(MSGS_FILE):
        return base
    with open(MSGS_FILE, 'r', encoding='utf-8') as f:
        saved = json.load(f)
    base.update(saved)
    return base

def save_mensagens(data):
    ensure_data_dir()
    with open(MSGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_status_aluguel(vencimento):
    d = datetime.today().day
    if d == vencimento: return 'vence-hoje'
    if d > vencimento:  return 'atrasado'
    return 'ok'

def get_chave_mes():
    h = datetime.today()
    return f"{h.year}-{h.month}"

def get_status_contrato(inq):
    c = inq.get('contrato', {})
    data_fim_str = c.get('data_fim', '')
    renovado     = c.get('renovado', False)
    if not data_fim_str:
        return {'status': 'sem_contrato', 'dias': None}
    try:
        data_fim = date.fromisoformat(data_fim_str)
    except ValueError:
        return {'status': 'sem_contrato', 'dias': None}
    delta = (data_fim - date.today()).days
    if renovado:
        return {'status': 'renovado', 'dias': delta, 'data_fim': data_fim_str}
    if delta < 0:
        return {'status': 'vencido',  'dias': abs(delta), 'data_fim': data_fim_str}
    if delta <= 30:
        return {'status': 'critico',  'dias': delta, 'data_fim': data_fim_str}
    if delta <= 60:
        return {'status': 'alerta',   'dias': delta, 'data_fim': data_fim_str}
    return {'status': 'ok', 'dias': delta, 'data_fim': data_fim_str}

# ── ROTAS ──────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/static/sw.js')
def service_worker():
    response = send_from_directory('static', 'sw.js')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/api/inquilinos', methods=['GET'])
def get_inquilinos():
    lista = load_inquilinos()
    chave = get_chave_mes()
    hoje  = datetime.today().day
    for i in lista:
        pago = i.get('pagos', {}).get(chave, False)
        i['_status']      = 'pago' if pago else get_status_aluguel(i['vencimento'])
        i['_dias_atraso'] = max(0, hoje - i['vencimento']) if i['_status'] == 'atrasado' else 0
        i['_contrato']    = get_status_contrato(i)
        i['_tem_pdf']     = os.path.exists(os.path.join(CONTRATOS_DIR, f"{i['id']}.pdf"))
    return jsonify(lista)

@app.route('/api/inquilinos', methods=['POST'])
def add_inquilino():
    data  = request.json
    lista = load_inquilinos()
    novo  = {
        'id': str(uuid.uuid4()), 'nome': data['nome'], 'whats': data['whats'],
        'endereco': data['endereco'], 'valor': str(data['valor']),
        'vencimento': int(data['vencimento']), 'pix': data.get('pix', ''),
        'pagos': {}, 'contrato': {}
    }
    lista.append(novo)
    save_inquilinos(lista)
    return jsonify(novo), 201

@app.route('/api/inquilinos/<id>', methods=['PUT'])
def update_inquilino(id):
    data  = request.json
    lista = load_inquilinos()
    for i in lista:
        if i['id'] == id:
            i.update({
                'nome': data.get('nome', i['nome']),
                'whats': data.get('whats', i['whats']),
                'endereco': data.get('endereco', i['endereco']),
                'valor': str(data.get('valor', i['valor'])),
                'vencimento': int(data.get('vencimento', i['vencimento'])),
                'pix': data.get('pix', i.get('pix', ''))
            })
            save_inquilinos(lista)
            return jsonify(i)
    return jsonify({'error': 'not found'}), 404

@app.route('/api/inquilinos/<id>', methods=['DELETE'])
def delete_inquilino(id):
    lista = [i for i in load_inquilinos() if i['id'] != id]
    save_inquilinos(lista)
    pdf = os.path.join(CONTRATOS_DIR, f"{id}.pdf")
    if os.path.exists(pdf): os.remove(pdf)
    return jsonify({'ok': True})

@app.route('/api/inquilinos/<id>/pago', methods=['POST'])
def marcar_pago(id):
    lista = load_inquilinos()
    chave = get_chave_mes()
    for i in lista:
        if i['id'] == id:
            i.setdefault('pagos', {})[chave] = True
            save_inquilinos(lista)
            return jsonify({'ok': True})
    return jsonify({'error': 'not found'}), 404

@app.route('/api/inquilinos/<id>/pago', methods=['DELETE'])
def desmarcar_pago(id):
    lista = load_inquilinos()
    chave = get_chave_mes()
    for i in lista:
        if i['id'] == id:
            i.get('pagos', {}).pop(chave, None)
            save_inquilinos(lista)
            return jsonify({'ok': True})
    return jsonify({'error': 'not found'}), 404

# contratos
@app.route('/api/inquilinos/<id>/contrato', methods=['GET'])
def get_contrato(id):
    lista = load_inquilinos()
    inq   = next((i for i in lista if i['id'] == id), None)
    if not inq: return jsonify({'error': 'not found'}), 404
    c = dict(inq.get('contrato', {}))
    c['tem_pdf']  = os.path.exists(os.path.join(CONTRATOS_DIR, f"{id}.pdf"))
    c['_status']  = get_status_contrato(inq)
    return jsonify(c)

@app.route('/api/inquilinos/<id>/contrato', methods=['POST'])
def save_contrato(id):
    data  = request.json
    lista = load_inquilinos()
    for i in lista:
        if i['id'] == id:
            c = i.setdefault('contrato', {})
            c['data_inicio']  = data.get('data_inicio', '')
            c['data_fim']     = data.get('data_fim', '')
            c['observacoes']  = data.get('observacoes', '')
            c['renovado']     = data.get('renovado', False)
            save_inquilinos(lista)
            return jsonify({'ok': True})
    return jsonify({'error': 'not found'}), 404

@app.route('/api/inquilinos/<id>/contrato/renovar', methods=['POST'])
def renovar_contrato(id):
    data  = request.json
    lista = load_inquilinos()
    for i in lista:
        if i['id'] == id:
            c = i.setdefault('contrato', {})
            c['data_inicio'] = data.get('data_inicio', '')
            c['data_fim']    = data.get('data_fim', '')
            c['renovado']    = False
            c['observacoes'] = data.get('observacoes', c.get('observacoes', ''))
            save_inquilinos(lista)
            return jsonify({'ok': True})
    return jsonify({'error': 'not found'}), 404

@app.route('/api/inquilinos/<id>/contrato/pdf', methods=['POST'])
def upload_pdf(id):
    ensure_data_dir()
    pdf_b64 = request.json.get('pdf_b64', '')
    if not pdf_b64: return jsonify({'error': 'no pdf'}), 400
    with open(os.path.join(CONTRATOS_DIR, f"{id}.pdf"), 'wb') as f:
        f.write(base64.b64decode(pdf_b64))
    return jsonify({'ok': True})

@app.route('/api/inquilinos/<id>/contrato/pdf', methods=['GET'])
def download_pdf(id):
    pdf_path = os.path.join(CONTRATOS_DIR, f"{id}.pdf")
    if not os.path.exists(pdf_path):
        return jsonify({'error': 'not found'}), 404
    return send_from_directory(CONTRATOS_DIR, f"{id}.pdf",
                               mimetype='application/pdf', as_attachment=False)

@app.route('/api/inquilinos/<id>/contrato/pdf', methods=['DELETE'])
def delete_pdf(id):
    pdf_path = os.path.join(CONTRATOS_DIR, f"{id}.pdf")
    if os.path.exists(pdf_path): os.remove(pdf_path)
    return jsonify({'ok': True})

@app.route('/api/alertas/contratos', methods=['GET'])
def alertas_contratos():
    lista = load_inquilinos()
    alertas = []
    for i in lista:
        st = get_status_contrato(i)
        if st['status'] in ('alerta', 'critico', 'vencido'):
            alertas.append({
                'id': i['id'], 'nome': i['nome'],
                'endereco': i.get('endereco', ''),
                'whats': i['whats'], 'contrato': st
            })
    return jsonify(alertas)

@app.route('/api/mensagens', methods=['GET'])
def get_mensagens():
    return jsonify(load_mensagens())

@app.route('/api/mensagens', methods=['POST'])
def update_mensagens():
    save_mensagens(request.json)
    return jsonify({'ok': True})

@app.route('/api/resumo', methods=['GET'])
def get_resumo():
    lista = load_inquilinos()
    chave = get_chave_mes()
    atrasados = vencem = em_dia = pagos = contratos_alerta = 0
    total = 0.0
    for i in lista:
        pago = i.get('pagos', {}).get(chave, False)
        st   = 'pago' if pago else get_status_aluguel(i['vencimento'])
        if st == 'atrasado':    atrasados += 1; total += float(i['valor'])
        elif st == 'vence-hoje': vencem += 1;   total += float(i['valor'])
        elif st == 'pago':      pagos += 1
        else:                   em_dia += 1
        if get_status_contrato(i)['status'] in ('alerta', 'critico', 'vencido'):
            contratos_alerta += 1
    return jsonify({
        'atrasados': atrasados, 'vencem_hoje': vencem,
        'em_dia': em_dia, 'pagos': pagos,
        'total_pendente': total, 'contratos_alerta': contratos_alerta
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
