import ast
import types
import sys
from pathlib import Path
import pytest
from flask import Flask, jsonify, current_app
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__); app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    db = SQLAlchemy(app)
    extension = types.ModuleType('db.extensions'); extension.db = db
    monkeypatch.setitem(sys.modules, 'db.extensions', extension)
    methods = types.ModuleType('services.payment_methods')
    exec(compile((ROOT/'services/payment_methods.py').read_text(), 'methods.py', 'exec'), methods.__dict__)
    package = types.ModuleType('services'); package.__path__ = []
    monkeypatch.setitem(sys.modules, 'services', package)
    monkeypatch.setitem(sys.modules, 'services.payment_methods', methods)
    tree = ast.parse((ROOT/'controllers/cafe_checkout_controller.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'gamer_payment_methods'); fn.decorator_list = []
    scope = dict(db=db, text=text, jsonify=jsonify, current_app=current_app)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), 'controller.py', 'exec'), scope)
    app.add_url_rule('/api/vendor/<int:vendor_id>/payment-methods', view_func=scope['gamer_payment_methods'])
    with app.app_context():
        for sql in ['CREATE TABLE vendors(id INTEGER PRIMARY KEY)', 'CREATE TABLE payment_method(pay_method_id INTEGER, method_name TEXT)', 'CREATE TABLE payment_vendor_map(vendor_id INTEGER, pay_method_id INTEGER)', 'INSERT INTO vendors VALUES(1),(2)', "INSERT INTO payment_method VALUES(1,'wallet'),(2,'pay_at_cafe')", 'INSERT INTO payment_vendor_map VALUES(1,1),(2,2)']:
            db.session.execute(text(sql))
        db.session.commit()
    yield app.test_client(), app, db

def test_dynamic_cafe_scoped_options(client):
    http, app, db = client
    initial = http.get('/api/vendor/1/payment-methods')
    assert initial.status_code == 200 and initial.headers['Cache-Control'] == 'no-store'
    assert initial.json['enabled_payment_methods'] == ['hash_wallet']
    assert len(initial.json['payment_methods']) == 6
    assert http.get('/api/vendor/2/payment-methods').json['enabled_payment_methods'] == ['pay_at_cafe']
    with app.app_context():
        db.session.execute(text('DELETE FROM payment_vendor_map WHERE vendor_id=1')); db.session.commit()
    assert http.get('/api/vendor/1/payment-methods').json['enabled_payment_methods'] == []

def test_missing_cafe_and_database_failure(client):
    http, app, db = client
    assert http.get('/api/vendor/99/payment-methods').status_code == 404
    with app.app_context():
        db.session.execute(text('DROP TABLE payment_vendor_map')); db.session.commit()
    response = http.get('/api/vendor/1/payment-methods')
    assert response.status_code == 503 and response.json['error'] == 'payment_methods_unavailable'
