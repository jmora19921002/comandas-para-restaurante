from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from pymysql import cursors
import pymysql
from decimal import Decimal
from functools import wraps
import json
from datetime import datetime,timedelta

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)  # Sesión expira después de 30 minutos
app.config['SESSION_REFRESH_EACH_REQUEST'] = True  # Refresca la sesión con cada solicitud

# Configuración de MySQL
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_PORT'] = 3306
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'TURING'
app.config['MYSQL_DB'] = 'comandas'

def get_db_connection():
    return pymysql.connect(
        host=app.config['MYSQL_HOST'],
        port=app.config['MYSQL_PORT'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB'],
        cursorclass=cursors.DictCursor
    )

# Decorador para verificar sesión
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Decorador para verificar rol de administrador
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario' not in session or session['usuario'].get('nombre_completo') != 'Admin':
            flash('Acceso denegado: Se requieren privilegios de administrador', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'usuario' in session:
        if session['usuario']['nombre_completo'] == 'Admin':
            return redirect(url_for('manager'))
        else:
            return redirect(url_for('comandas'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        password = request.form['password']
        
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM usuario WHERE user = %s AND password = %s AND estatus = 'activo'", (usuario, password))
            user = cur.fetchone()
            cur.close()
            conn.close()
            
            if user:
                session['usuario'] = {
                    'user': user['user'],
                    'nombre_completo': user['nombre_completo']
                }
                flash('Inicio de sesión exitoso', 'success')
                return redirect(url_for('index'))
            else:
                flash('Usuario o contraseña incorrectos', 'error')
        except Exception as e:
            flash(f'Error de conexión: {str(e)}', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión correctamente', 'info')
    return redirect(url_for('login'))

@app.route('/comandas')
@login_required
def comandas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Obtener mesas
        cur.execute("SELECT Id, nombre, estatus FROM mesas ORDER BY nombre")
        mesas = cur.fetchall()
        
        # Obtener grupos
        cur.execute("SELECT codigo, nombre FROM grupos ORDER BY nombre")
        grupos = cur.fetchall()
        
        # Obtener items (solo activos con existencia) - Añadido grupo_codigo
        cur.execute("""
            SELECT i.id, i.nombre, i.precio, i.grupo_codigo, g.nombre as grupo 
            FROM item i 
            JOIN grupos g ON i.grupo_codigo = g.codigo 
            WHERE i.estatus = 'activo' AND i.existencia > 0
            ORDER BY i.nombre
        """)
        items = cur.fetchall()
        
        # Convertir Decimal a float para JSON
        items_json = []
        for item in items:
            items_json.append({
                'id': item['id'],
                'nombre': item['nombre'],
                'precio': float(item['precio']),
                'grupo': item['grupo'],
                'grupo_codigo': item['grupo_codigo']
            })
        
        return render_template('comandas.html', 
                            mesas=mesas, 
                            grupos=grupos, 
                            items=json.dumps(items_json),
                            usuario=session['usuario'])
    except Exception as e:
        flash(f'Error al cargar comandas: {str(e)}', 'error')
        return redirect(url_for('index'))
    finally:
        cur.close()
        conn.close()

@app.route('/manager')
@login_required
@admin_required
def manager():
    return render_template('manager.html', usuario=session['usuario'])

# Secciones del Manager
@app.route('/manager/usuarios')
@login_required
@admin_required
def manager_usuarios():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, user, nombre_completo, estatus FROM usuario")
        usuarios = cur.fetchall()
        return render_template('partials/usuarios.html', usuarios=usuarios)
    except Exception as e:
        flash(f'Error al cargar usuarios: {str(e)}', 'error')
        return render_template('partials/usuarios.html', usuarios=[])
    finally:
        cur.close()
        conn.close()

@app.route('/manager/items')
@login_required
@admin_required
def manager_items():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT i.id, i.nombre, i.precio, i.existencia, i.estatus, g.nombre as grupo 
            FROM item i 
            JOIN grupos g ON i.grupo_codigo = g.codigo
            ORDER BY i.nombre
        """)
        items = cur.fetchall()
        
        # Convertir Decimal a float para la plantilla
        for item in items:
            item['precio'] = float(item['precio'])
        
        cur.execute("SELECT codigo, nombre FROM grupos ORDER BY nombre")
        grupos = cur.fetchall()
        
        return render_template('partials/items.html', items=items, grupos=grupos)
    except Exception as e:
        flash(f'Error al cargar items: {str(e)}', 'error')
        return render_template('partials/items.html', items=[], grupos=[])
    finally:
        cur.close()
        conn.close()

@app.route('/api/items', methods=['POST'])
@login_required
@admin_required
def api_create_item():
    try:
        data = request.get_json()
        
        # Validación de campos requeridos
        required_fields = ['nombre', 'grupo_codigo', 'precio', 'existencia', 'estatus']
        if not all(field in data for field in required_fields):
            return jsonify({
                'success': False,
                'message': 'Todos los campos son requeridos: nombre, grupo_codigo, precio, existencia, estatus'
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        # Verificar que el grupo existe
        cur.execute("SELECT 1 FROM grupos WHERE codigo = %s", (data['grupo_codigo'],))
        if not cur.fetchone():
            return jsonify({
                'success': False,
                'message': 'El grupo seleccionado no existe'
            }), 400

        # Insertar nuevo ítem
        cur.execute("""
            INSERT INTO item (nombre, grupo_codigo, precio, existencia, estatus)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            data['nombre'],
            data['grupo_codigo'],
            Decimal(str(data['precio'])),
            int(data['existencia']),
            data['estatus']
        ))

        conn.commit()
        return jsonify({
            'success': True,
            'message': 'Ítem creado correctamente',
            'id': cur.lastrowid
        })

    except Exception as e:
        conn.rollback()
        return jsonify({
            'success': False,
            'message': f'Error al crear el ítem: {str(e)}'
        }), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/items/<int:item_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_item(item_id):
    try:
        print(f"Recibida solicitud PUT para item {item_id}")  # Agrega esto
        data = request.get_json()
        print(f"Datos recibidos: {data}")
        
        # Validación de campos requeridos
        required_fields = ['nombre', 'grupo_codigo', 'precio', 'existencia', 'estatus']
        if not all(field in data for field in required_fields):
            return jsonify({
                'success': False,
                'message': 'Todos los campos son requeridos: nombre, grupo_codigo, precio, existencia, estatus'
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        # Verificar que el ítem existe
        cur.execute("SELECT 1 FROM item WHERE id = %s", (item_id,))
        if not cur.fetchone():
            return jsonify({
                'success': False,
                'message': 'El ítem no existe'
            }), 404

        # Verificar que el grupo existe
        cur.execute("SELECT 1 FROM grupos WHERE codigo = %s", (data['grupo_codigo'],))
        if not cur.fetchone():
            return jsonify({
                'success': False,
                'message': 'El grupo seleccionado no existe'
            }), 400

        # Actualizar ítem
        cur.execute("""
            UPDATE item 
            SET nombre = %s, 
                grupo_codigo = %s, 
                precio = %s, 
                existencia = %s, 
                estatus = %s
            WHERE id = %s
        """, (
            data['nombre'],
            data['grupo_codigo'],
            Decimal(str(data['precio'])),
            int(data['existencia']),
            data['estatus'],
            item_id
        ))

        conn.commit()
        return jsonify({
            'success': True,
            'message': 'Ítem actualizado correctamente'
        })

    except Exception as e:
        conn.rollback()
        return jsonify({
            'success': False,
            'message': f'Error al actualizar el ítem: {str(e)}'
        }), 500
    finally:
        cur.close()
        conn.close()

@app.route('/manager/grupos')
@login_required
@admin_required
def manager_grupos():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT codigo, nombre FROM grupos ORDER BY nombre")
        grupos = cur.fetchall()
        return render_template('partials/grupos.html', grupos=grupos)
    except Exception as e:
        flash(f'Error al cargar grupos: {str(e)}', 'error')
        return render_template('partials/grupos.html', grupos=[])
    finally:
        cur.close()
        conn.close()

@app.route('/manager/mesas')
@login_required
@admin_required
def manager_mesas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT Id, nombre, estatus FROM mesas ORDER BY nombre")
        mesas = cur.fetchall()
        return render_template('partials/mesas.html', mesas=mesas)
    except Exception as e:
        flash(f'Error al cargar mesas: {str(e)}', 'error')
        return render_template('partials/mesas.html', mesas=[])
    finally:
        cur.close()
        conn.close()

@app.route('/manager/comandas')
@login_required
@admin_required
def manager_comandas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, m.nombre as mesa, c.total, c.fecha, c.estatus, u.nombre_completo as usuario
            FROM comandas c
            JOIN mesas m ON c.mesa_id = m.Id
            JOIN usuario u ON c.usuario_id = u.id
            ORDER BY c.fecha DESC
        """)
        comandas = cur.fetchall()
        
        # Convertir Decimal a float
        for comanda in comandas:
            comanda['total'] = float(comanda['total'])
            
        return render_template('partials/comandas_list.html', comandas=comandas)
    except Exception as e:
        flash(f'Error al cargar comandas: {str(e)}', 'error')
        return render_template('partials/comandas_list.html', comandas=[])
    finally:
        cur.close()
        conn.close()

@app.route('/formulario/<tipo>')
@login_required
@admin_required
def mostrar_formulario(tipo):
    id = request.args.get('id')
    
    if tipo == 'usuarios':
        if id:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM usuario WHERE id = %s", (id,))
            registro = cur.fetchone()
            cur.close()
            conn.close()
            return render_template('partials/form_usuario.html', usuario=registro)
        return render_template('partials/form_usuario.html')
    
    elif tipo == 'item':
        # Obtener grupos para el select
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT codigo, nombre FROM grupos ORDER BY nombre")
        grupos = cur.fetchall()
        
        item = None
        if id:
            cur.execute("SELECT * FROM item WHERE id = %s", (id,))
            item = cur.fetchone()
            if item and 'precio' in item:
                item['precio'] = float(item['precio'])
        
        cur.close()
        conn.close()
        
        return render_template('partials/form_item.html', item=item, grupos=grupos)
    
    # Si el tipo no es reconocido
    return "Tipo de formulario no válido", 404
    
@app.route('/formulario/usuarios')
@login_required
@admin_required
def formulario_usuario():
    usuario_id = request.args.get('id')
    usuario = None
    
    if usuario_id:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuario WHERE id = %s", (usuario_id,))
        usuario = cur.fetchone()
        cur.close()
        conn.close()
    
    return render_template('partials/form_usuario.html', usuario=usuario)

@app.route('/manager/ventas-item')
@login_required
@admin_required
def manager_ventas_item():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Consulta para ventas por ítem
        cur.execute("""
            SELECT i.nombre as item, SUM(cd.cantidad) as cantidad, 
                   SUM(cd.total) as total
            FROM comanda_detalle cd
            JOIN item i ON cd.item_id = i.id
            JOIN comandas c ON cd.comanda_id = c.id
            GROUP BY i.nombre
            ORDER BY total DESC
        """)
        ventas_items = cur.fetchall()
        
        # Calcular total general
        total_ventas = sum(float(item['total']) for item in ventas_items)
        
        # Convertir Decimal a float
        for item in ventas_items:
            item['total'] = float(item['total'])
            
        return render_template('partials/ventas_item.html', 
                            ventas_items=ventas_items,
                            total_ventas=total_ventas)
    except Exception as e:
        flash(f'Error al cargar ventas por ítem: {str(e)}', 'error')
        return render_template('partials/ventas_item.html', 
                              ventas_items=[], 
                              total_ventas=0)
    finally:
        cur.close()
        conn.close()
# API Endpoints para el manager


@app.route('/api/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def api_usuarios():
    if request.method == 'GET':
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, user, nombre_completo, estatus FROM usuario")
            usuarios = cur.fetchall()
            return jsonify(usuarios)
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 400
        finally:
            cur.close()
            conn.close()
    
    elif request.method == 'POST':
        data = request.get_json()
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO usuario (user, password, nombre_completo, estatus)
                VALUES (%s, %s, %s, %s)
            """, (data['user'], data['password'], data['nombre_completo'], data['estatus']))
            conn.commit()
            return jsonify({'success': True, 'message': 'Usuario creado correctamente'})
        except Exception as e:
            conn.rollback()
            return jsonify({'success': False, 'message': str(e)}), 400
        finally:
            cur.close()
            conn.close()

@app.route('/api/usuarios/<int:user_id>', methods=['PUT', 'DELETE'])
@login_required
@admin_required
def api_usuario(user_id):
    if request.method == 'PUT':
        data = request.get_json()
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            if 'password' in data and data['password']:
                cur.execute("""
                    UPDATE usuario 
                    SET user=%s, password=%s, nombre_completo=%s, estatus=%s 
                    WHERE id=%s
                """, (data['user'], data['password'], data['nombre_completo'], data['estatus'], user_id))
            else:
                cur.execute("""
                    UPDATE usuario 
                    SET user=%s, nombre_completo=%s, estatus=%s 
                    WHERE id=%s
                """, (data['user'], data['nombre_completo'], data['estatus'], user_id))
                
            conn.commit()
            return jsonify({'success': True, 'message': 'Usuario actualizado correctamente'})
        except Exception as e:
            conn.rollback()
            return jsonify({'success': False, 'message': str(e)}), 400
        finally:
            cur.close()
            conn.close()
    
    elif request.method == 'DELETE':
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM usuario WHERE id = %s", (user_id,))
            conn.commit()
            return jsonify({'success': True, 'message': 'Usuario eliminado correctamente'})
        except Exception as e:
            conn.rollback()
            return jsonify({'success': False, 'message': str(e)}), 400
        finally:
            cur.close()
            conn.close()

@app.route('/api/comandas', methods=['POST'])
@login_required
def api_guardar_comanda():
    data = request.get_json()
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Guardar comanda
        cur.execute("""
            INSERT INTO comandas (mesa_id, total, estatus, usuario_id)
            VALUES (%s, %s, 'pendiente', 
                (SELECT id FROM usuario WHERE user = %s))
        """, (data['mesa_id'], data['total'], session['usuario']['user']))
        
        comanda_id = cur.lastrowid
        
        # Guardar detalles
        for item in data['items']:
            cur.execute("""
                INSERT INTO comanda_detalle 
                (comanda_id, item_id, cantidad, precio_unitario, total)
                VALUES (%s, %s, %s, %s, %s)
            """, (comanda_id, item['id'], item['cantidad'], item['precio'], item['total']))
        
        # Actualizar estado de la mesa
        cur.execute("UPDATE mesas SET estatus = 'ocupada' WHERE Id = %s", (data['mesa_id'],))
        
        conn.commit()
        return jsonify({
            'success': True,
            'message': 'Comanda guardada correctamente',
            'comanda_id': comanda_id
        })
    except Exception as e:
        conn.rollback()
        return jsonify({
            'success': False,
            'message': f'Error al guardar comanda: {str(e)}'
        }), 400
    finally:
        cur.close()
        conn.close()
# Agrega estas rutas API para items en app.py
@app.route('/api/items', methods=['GET', 'POST'])
@login_required
@admin_required
def api_items():
    if request.method == 'GET':
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT i.id, i.nombre, i.precio, i.existencia, i.estatus, 
                       g.codigo as grupo_codigo, g.nombre as grupo_nombre
                FROM item i 
                JOIN grupos g ON i.grupo_codigo = g.codigo
                ORDER BY i.nombre
            """)
            items = cur.fetchall()
            
            # Convertir Decimal a float
            for item in items:
                item['precio'] = float(item['precio'])
                
            return jsonify(items)
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 400
        finally:
            cur.close()
            conn.close()
    
    elif request.method == 'POST':
        data = request.get_json()
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO item (nombre, grupo_codigo, precio, existencia, estatus)
                VALUES (%s, %s, %s, %s, %s)
            """, (data['nombre'], data['grupo_codigo'], data['precio'], 
                 data['existencia'], data['estatus']))
            conn.commit()
            return jsonify({'success': True, 'message': 'Item creado correctamente'})
        except Exception as e:
            conn.rollback()
            return jsonify({'success': False, 'message': str(e)}), 400
        finally:
            cur.close()
            conn.close()

@app.route('/api/items/<int:item_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
@admin_required
def api_item(item_id):
    if request.method == 'GET':
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT i.id, i.nombre, i.precio, i.existencia, i.estatus, 
                       g.codigo as grupo_codigo, g.nombre as grupo_nombre
                FROM item i 
                JOIN grupos g ON i.grupo_codigo = g.codigo
                WHERE i.id = %s
            """, (item_id,))
            item = cur.fetchone()
            
            if item:
                item['precio'] = float(item['precio'])
                return jsonify(item)
            else:
                return jsonify({'success': False, 'message': 'Item no encontrado'}), 404
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 400
        finally:
            cur.close()
            conn.close()
    
    elif request.method == 'PUT':
        data = request.get_json()
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE item 
                SET nombre=%s, grupo_codigo=%s, precio=%s, existencia=%s, estatus=%s
                WHERE id=%s
            """, (data['nombre'], data['grupo_codigo'], data['precio'], 
                 data['existencia'], data['estatus'], item_id))
            conn.commit()
            return jsonify({'success': True, 'message': 'Item actualizado correctamente'})
        except Exception as e:
            conn.rollback()
            return jsonify({'success': False, 'message': str(e)}), 400
        finally:
            cur.close()
            conn.close()
    
    elif request.method == 'DELETE':
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM item WHERE id = %s", (item_id,))
            conn.commit()
            return jsonify({'success': True, 'message': 'Item eliminado correctamente'})
        except Exception as e:
            conn.rollback()
            return jsonify({'success': False, 'message': str(e)}), 400
        finally:
            cur.close()
            conn.close()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)