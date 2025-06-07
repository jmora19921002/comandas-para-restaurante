from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from models import db, Usuario, Grupo, Item, Mesa, Comanda, ComandaDetalle
from forms import LoginForm, UsuarioForm, ItemForm, GrupoForm, MesaForm
from datetime import datetime

main_bp = Blueprint('main', __name__)
auth_bp = Blueprint('auth', __name__)
manager_bp = Blueprint('manager', __name__, url_prefix='/manager')
comandas_bp = Blueprint('comandas', __name__, url_prefix='/comandas')

@main_bp.route('/')
def index():
    return redirect(url_for('auth.login'))

# Autenticación
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        usuario = Usuario.query.filter_by(user=form.usuario.data).first()
        if usuario and usuario.check_password(form.password.data):
            login_user(usuario)
            if usuario.nombre_completo == "Administrador":
                return redirect(url_for('manager.dashboard'))
            return redirect(url_for('comandas.index'))
        flash('Usuario o contraseña incorrectos')
    return render_template('login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

# Módulo de Comandas
@comandas_bp.route('/')
@login_required
def index():
    mesas = Mesa.query.order_by(Mesa.nombre).all()
    grupos = Grupo.query.order_by(Grupo.nombre).all()
    return render_template('comandas.html', mesas=mesas, grupos=grupos)

@comandas_bp.route('/mesa/<int:mesa_id>')
@login_required
def cargar_mesa(mesa_id):
    mesa = Mesa.query.get_or_404(mesa_id)
    comanda = Comanda.query.filter_by(mesa_id=mesa_id, estatus='pendiente').first()
    
    items = []
    total = 0.0
    
    if comanda:
        for detalle in comanda.detalles:
            items.append({
                'id': detalle.item_id,
                'nombre': detalle.item.nombre,
                'precio': float(detalle.precio_unitario),
                'cantidad': detalle.cantidad,
                'total': float(detalle.total)
            })
            total += float(detalle.total)
    
    return jsonify({
        'mesa': {'id': mesa.Id, 'nombre': mesa.nombre, 'estatus': mesa.estatus},
        'items': items,
        'total': total,
        'comanda_id': comanda.id if comanda else None
    })

@comandas_bp.route('/agregar_item', methods=['POST'])
@login_required
def agregar_item():
    data = request.get_json()
    mesa_id = data['mesa_id']
    item_id = data['item_id']
    
    mesa = Mesa.query.get_or_404(mesa_id)
    item = Item.query.get_or_404(item_id)
    
    # Buscar comanda existente o crear nueva
    comanda = Comanda.query.filter_by(mesa_id=mesa_id, estatus='pendiente').first()
    
    if not comanda:
        comanda = Comanda(mesa_id=mesa_id, usuario_id=current_user.id, total=0)
        db.session.add(comanda)
        mesa.estatus = 'ocupada'
    
    # Buscar si el item ya está en la comanda
    detalle = next((d for d in comanda.detalles if d.item_id == item_id), None)
    
    if detalle:
        detalle.cantidad += 1
        detalle.total = detalle.cantidad * detalle.precio_unitario
    else:
        detalle = ComandaDetalle(
            comanda_id=comanda.id,
            item_id=item_id,
            cantidad=1,
            precio_unitario=item.precio,
            total=item.precio
        )
        db.session.add(detalle)
    
    # Actualizar total de la comanda
    comanda.total = sum(d.total for d in comanda.detalles)
    
    db.session.commit()
    
    return jsonify({'success': True})

@comandas_bp.route('/imprimir_comanda/<int:comanda_id>')
@login_required
def imprimir_comanda(comanda_id):
    comanda = Comanda.query.get_or_404(comanda_id)
    return render_template('comandas_detalle.html', comanda=comanda)

# Módulo de Manager
@manager_bp.route('/')
@login_required
def dashboard():
    if current_user.nombre_completo != "Administrador":
        flash('Acceso denegado: Solo para administradores')
        return redirect(url_for('comandas.index'))
    return render_template('manager.html')

# CRUD Usuarios
@manager_bp.route('/usuarios')
@login_required
def usuarios():
    usuarios = Usuario.query.all()
    return render_template('usuarios.html', usuarios=usuarios)

@manager_bp.route('/usuario/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_usuario():
    form = UsuarioForm()
    if form.validate_on_submit():
        usuario = Usuario(
            user=form.usuario.data,
            nombre_completo=form.nombre_completo.data,
            estatus=form.estatus.data
        )
        usuario.set_password(form.password.data)
        db.session.add(usuario)
        db.session.commit()
        flash('Usuario creado exitosamente')
        return redirect(url_for('manager.usuarios'))
    return render_template('usuario_form.html', form=form)

# CRUD Items
@manager_bp.route('/items')
@login_required
def items():
    items = Item.query.all()
    return render_template('items.html', items=items)

@manager_bp.route('/item/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_item():
    form = ItemForm()
    form.grupo_codigo.choices = [(g.codigo, g.nombre) for g in Grupo.query.all()]
    
    if form.validate_on_submit():
        item = Item(
            nombre=form.nombre.data,
            grupo_codigo=form.grupo_codigo.data,
            precio=form.precio.data,
            existencia=form.existencia.data,
            estatus=form.estatus.data
        )
        db.session.add(item)
        db.session.commit()
        flash('Ítem creado exitosamente')
        return redirect(url_for('manager.items'))
    return render_template('item_form.html', form=form)

# CRUD Grupos
@manager_bp.route('/grupos')
@login_required
def grupos():
    grupos = Grupo.query.all()
    return render_template('grupos.html', grupos=grupos)

@manager_bp.route('/grupo/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_grupo():
    form = GrupoForm()
    if form.validate_on_submit():
        grupo = Grupo(
            codigo=form.codigo.data,
            nombre=form.nombre.data,
            formato=form.formato.data
        )
        db.session.add(grupo)
        db.session.commit()
        flash('Grupo creado exitosamente')
        return redirect(url_for('manager.grupos'))
    return render_template('grupo_form.html', form=form)

# CRUD Mesas
@manager_bp.route('/mesas')
@login_required
def mesas():
    mesas = Mesa.query.all()
    return render_template('mesas.html', mesas=mesas)

@manager_bp.route('/mesa/nuevo', methods=['GET', 'POST'])
@login_required
def nueva_mesa():
    form = MesaForm()
    if form.validate_on_submit():
        mesa = Mesa(
            nombre=form.nombre.data,
            estatus=form.estatus.data
        )
        db.session.add(mesa)
        db.session.commit()
        flash('Mesa creada exitosamente')
        return redirect(url_for('manager.mesas'))
    return render_template('mesa_form.html', form=form)

# Reportes
@manager_bp.route('/ventas')
@login_required
def ventas():
    return render_template('ventas.html')

@manager_bp.route('/ventas_por_item')
@login_required
def ventas_por_item():
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    item_id = request.args.get('item_id')
    
    query = db.session.query(
        ComandaDetalle.item_id,
        Item.nombre,
        db.func.sum(ComandaDetalle.cantidad).label('total_cantidad'),
        db.func.sum(ComandaDetalle.total).label('total_venta')
    ).join(Item).join(Comanda)
    
    if fecha_inicio:
        query = query.filter(Comanda.fecha >= fecha_inicio)
    if fecha_fin:
        query = query.filter(Comanda.fecha <= fecha_fin)
    if item_id:
        query = query.filter(ComandaDetalle.item_id == item_id)
    
    ventas = query.group_by(ComandaDetalle.item_id, Item.nombre).all()
    
    return jsonify([{
        'item_id': v.item_id,
        'nombre': v.nombre,
        'cantidad': v.total_cantidad,
        'total': float(v.total_venta)
    } for v in ventas])