    # 文件: app.py
    # 描述: 实验室库存管理系统的后端API服务
    #
    # --- 运行前准备 ---
    # 1. 安装必要的库 (在终端或命令行中运行):
    #    pip install Flask Flask-Cors supabase python-dotenv gunicorn
    #
    # 2. 创建 .env 文件:
    #    在与此 app.py 文件相同的目录下创建一个名为 .env 的文件。
    #
    # 3. 配置 .env 文件:
    #    将您的 Supabase URL 和 Key 添加到 .env 文件中，格式如下：
    #    SUPABASE_URL="https://djmufwaugvkljirxrumd.supabase.co"
    #    SUPABASE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRqbXVmd2F1Z3ZrbGppcnhydW1kIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTQzMjE5ODUsImV4cCI6MjA2OTg5Nzk4NX0.fEeb5XLHWXKBFMSoURjLszhaz8CHQtm7Sr3ZN4Y7HlY"
    #
    # 4. 本地运行 (在终端或命令行中运行):
    #    python app.py
    #
    #    API服务将在 http://12.0.0.1:5000 启动。
    #
    # 5. 生产环境运行 (由Render等平台自动执行):
    #    gunicorn app:app

    import os
    from flask import Flask, jsonify, request
    from flask_cors import CORS
    from supabase import create_client, Client
    from dotenv import load_dotenv
    from datetime import datetime, timedelta

    # 加载 .env 文件中的环境变量
    load_dotenv()

    # 初始化 Flask 应用
    app = Flask(__name__)
    # 启用CORS，允许前端页面(通常来自不同源)访问API
    CORS(app) 

    # 从环境变量中获取 Supabase 的连接信息并创建客户端
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")

    # 检查URL和Key是否存在，如果不存在则程序会因无法连接而失败
    if not url or not key:
        raise ValueError("Supabase URL and Key must be set in the .env file.")

    supabase: Client = create_client(url, key)

    # --- API Endpoints (API接口) ---

    @app.route('/api/dashboard', methods=['GET'])
    def get_dashboard_data():
        """获取总控面板所需的数据 (最近记录和临期试剂)"""
        try:
            # 1. 获取最近5条操作记录
            records_res = supabase.table('records').select('*').order('time', desc=True).limit(5).execute()
            
            # 2. 获取临近过期的试剂批次 (30天内)
            # 计算30天后的日期
            warning_days = 30
            today = datetime.now().date()
            thirty_days_later = today + timedelta(days=warning_days)
            
            # 查询有效期在今天和30天后之间的批次
            expiring_batches_res = supabase.table('reagent_batches').select('*, reagents(name)') \
                .gte('exp_date', today.isoformat()) \
                .lte('exp_date', thirty_days_later.isoformat()) \
                .execute()

            expiring_soon = []
            for batch in expiring_batches_res.data:
                exp_date = datetime.strptime(batch['exp_date'], '%Y-%m-%d').date()
                days_left = (exp_date - today).days
                expiring_soon.append({
                    'reagentName': batch['reagents']['name'] if batch.get('reagents') else '未知试剂',
                    'batch': { 'batchNo': batch['batch_no'] },
                    'daysLeft': days_left
                })
            
            # 按剩余天数升序排序
            expiring_soon.sort(key=lambda x: x['daysLeft'])

            return jsonify({
                'recentRecords': records_res.data,
                'expiringSoon': expiring_soon[:5] # 只返回前5个
            })
        except Exception as e:
            return jsonify({'error': f"获取总控面板数据失败: {e}"}), 500

    @app.route('/api/reagents', methods=['GET'])
    def get_reagents():
        """获取所有试剂及其所有批次信息"""
        try:
            # 使用嵌套查询一次性获取试剂和其所有批次 (reagent_batches)
            response = supabase.table('reagents').select('*, reagent_batches(*)').order('name').execute()
            return jsonify(response.data)
        except Exception as e:
            return jsonify({'error': f"获取试剂列表失败: {e}"}), 500

    @app.route('/api/equipment', methods=['GET'])
    def get_equipment():
        """获取所有设备及其所有维护记录"""
        try:
            # 使用嵌套查询一次性获取设备和其所有维护记录 (maintenance_logs)
            response = supabase.table('equipment').select('*, maintenance_logs(*)').order('created_at', desc=True).execute()
            return jsonify(response.data)
        except Exception as e:
            return jsonify({'error': f"获取设备列表失败: {e}"}), 500

    @app.route('/api/records', methods=['GET'])
    def get_records():
        """获取所有操作记录"""
        try:
            # 实际应用中可以根据前端传来的参数进行筛选和分页
            response = supabase.table('records').select('*').order('time', desc=True).execute()
            return jsonify(response.data)
        except Exception as e:
            return jsonify({'error': f"获取操作记录失败: {e}"}), 500

    @app.route('/api/reagents/in', methods=['POST'])
    def reagent_in():
        """处理试剂入库请求"""
        data = request.json
        try:
            # 1. 查找或创建试剂主条目
            reagent_res = supabase.table('reagents').select('id').eq('name', data['name']).execute()
            reagent_id = None
            if reagent_res.data:
                reagent_id = reagent_res.data[0]['id']
                # --- BUG修复 START ---
                # 旧逻辑: 只更新分类
                # supabase.table('reagents').update({'category': data.get('category', '未分类')}).eq('id', reagent_id).execute()
                
                # 新逻辑: 完整更新试剂的基础信息 (货号、制造商、分类)
                update_payload = {
                    'article_no': data['articleNo'],
                    'manufacturer': data['manufacturer'],
                    'category': data.get('category', '未分类')
                }
                supabase.table('reagents').update(update_payload).eq('id', reagent_id).execute()
                # --- BUG修复 END ---
            else:
                # 如果试剂不存在，创建新的试剂条目
                new_reagent = supabase.table('reagents').insert({
                    'name': data['name'],
                    'article_no': data['articleNo'],
                    'manufacturer': data['manufacturer'],
                    'category': data.get('category', '未分类')
                }).execute()
                reagent_id = new_reagent.data[0]['id']

            # 2. 智能批次处理
            batch_details = data['batchDetails']
            
            # 查找是否存在属性完全匹配的现有批次
            existing_batch_res = supabase.table('reagent_batches').select('id, total_tests').eq('reagent_id', reagent_id).eq('batch_no', batch_details['batchNo']).eq('prod_date', batch_details['prodDate']).eq('exp_date', batch_details['expDate']).eq('tests_per_unit', batch_details['testsPerUnit']).eq('location', batch_details['location']).eq('temp', batch_details['temp']).execute()
            
            total_in = data['qty'] * batch_details['testsPerUnit']

            if existing_batch_res.data:
                # 如果找到，合并库存到现有批次
                existing_batch = existing_batch_res.data[0]
                new_total = existing_batch['total_tests'] + total_in
                supabase.table('reagent_batches').update({'total_tests': new_total}).eq('id', existing_batch['id']).execute()
                log_notes = f"合并入库 {data['qty']} 盒"
            else:
                # 如果没找到，创建新批次
                supabase.table('reagent_batches').insert({
                    'reagent_id': reagent_id,
                    'batch_no': batch_details['batchNo'],
                    'prod_date': batch_details['prodDate'],
                    'exp_date': batch_details['expDate'],
                    'total_tests': total_in,
                    'tests_per_unit': batch_details['testsPerUnit'],
                    'location': batch_details['location'],
                    'temp': batch_details['temp']
                }).execute()
                log_notes = f"新批次入库 {data['qty']} 盒"

            # 3. 记录操作日志
            log_record('入库', '试剂', data['name'], batch_details['batchNo'], total_in, data['operator'], log_notes)

            return jsonify({'message': '入库成功'}), 201
        except Exception as e:
            return jsonify({'error': f"试剂入库失败: {e}"}), 500

    @app.route('/api/reagents/out', methods=['POST'])
    def reagent_out():
        """处理试剂出库"""
        data = request.json
        try:
            # 使用唯一的 batchId (批次ID) 来精确定位要出库的库存条目
            batch_id = data['batchId']
            batch_res = supabase.table('reagent_batches').select('id, total_tests').eq('id', batch_id).single().execute()

            if not batch_res.data:
                return jsonify({'error': '批次未找到'}), 404
            
            batch = batch_res.data
            amount_out = int(data['amount'])

            if amount_out <= 0 or amount_out > batch['total_tests']:
                return jsonify({'error': '出库数量无效或超过库存'}), 400
            
            # 2. 更新库存
            new_total = batch['total_tests'] - amount_out
            if new_total > 0:
                supabase.table('reagent_batches').update({'total_tests': new_total}).eq('id', batch['id']).execute()
            else:
                # 如果库存耗尽，删除该批次记录
                supabase.table('reagent_batches').delete().eq('id', batch['id']).execute()

            # 3. 记录操作日志
            log_record('出库', '试剂', data['reagentName'], data['batchNo'], amount_out, data['user'], data['purpose'])

            return jsonify({'message': '出库成功'}), 200
        except Exception as e:
            return jsonify({'error': f"试剂出库失败: {e}"}), 500


    @app.route('/api/equipment', methods=['POST'])
    def equipment_in():
        """设备登记"""
        data = request.json
        try:
            # 检查序列号唯一性 (如果提供了序列号)
            if data.get('serialNo'):
                existing = supabase.table('equipment').select('id').eq('serial_no', data['serialNo']).execute()
                if existing.data:
                    return jsonify({'error': '该出厂编号已存在'}), 409
            
            new_equip = {
                'name': data['name'],
                'manufacturer': data.get('manufacturer'),
                'model': data.get('model'),
                'serial_no': data.get('serialNo') or None, # 确保空字符串存为NULL
                'quantity': 1 if data.get('serialNo') else int(data.get('quantity', 1)),
                'location': data.get('location'),
                'status': data.get('status'),
                'purchase_date': data.get('purchaseDate') or None,
                'deployment_date': data.get('deploymentDate') or None,
                'warranty_date': data.get('warrantyDate') or None,
                'person_in_charge': data.get('personInCharge')
            }
            
            inserted = supabase.table('equipment').insert(new_equip).execute()
            
            log_record('设备登记', '设备', new_equip['name'], new_equip['serial_no'] or new_equip['model'], new_equip['quantity'], data.get('operator'), '')
            
            return jsonify(inserted.data[0]), 201
        except Exception as e:
            return jsonify({'error': f"设备登记失败: {e}"}), 500

    @app.route('/api/equipment/<uuid:equip_id>', methods=['PUT'])
    def equipment_edit(equip_id):
        """编辑设备信息"""
        data = request.json
        try:
            update_data = {
                'manufacturer': data.get('manufacturer'),
                'location': data.get('location'),
                'status': data.get('status'),
                'quantity': int(data.get('quantity', 1)),
                'purchase_date': data.get('purchaseDate') or None,
                'deployment_date': data.get('deploymentDate') or None,
                'warranty_date': data.get('warrantyDate') or None,
                'person_in_charge': data.get('personInCharge')
            }
            
            updated = supabase.table('equipment').update(update_data).eq('id', str(equip_id)).execute()
            
            if not updated.data:
                return jsonify({'error': '设备未找到'}), 404
                
            log_record('设备编辑', '设备', updated.data[0]['name'], updated.data[0]['serial_no'] or updated.data[0]['model'], update_data['quantity'], data.get('operator'), '更新信息')
            
            return jsonify(updated.data[0]), 200
        except Exception as e:
            return jsonify({'error': f"设备编辑失败: {e}"}), 500

    @app.route('/api/equipment/<uuid:equip_id>/maintenance', methods=['POST'])
    def add_maintenance_log(equip_id):
        """添加设备维护记录"""
        data = request.json
        try:
            new_log = {
                'equipment_id': str(equip_id),
                'log_date': data['date'],
                'log_type': data['type'],
                'notes': data['notes'],
                'operator': data['operator']
            }
            
            inserted = supabase.table('maintenance_logs').insert(new_log).execute()
            
            # 获取设备信息用于记录
            equip_info = supabase.table('equipment').select('name, serial_no, model').eq('id', str(equip_id)).single().execute()
            log_record('设备维护', '设备', equip_info.data['name'], equip_info.data['serial_no'] or equip_info.data['model'], 1, new_log['operator'], f"{new_log['log_type']}: {new_log['notes']}")
            
            return jsonify(inserted.data[0]), 201
        except Exception as e:
            return jsonify({'error': f"添加维护记录失败: {e}"}), 500

    # --- Helper Functions ---
    def log_record(type, item_type, name, batch_or_serial, qty, operator, notes):
        """通用日志记录函数"""
        try:
            supabase.table('records').insert({
                'type': type,
                'item_type': item_type,
                'name': name,
                'batch_or_serial': batch_or_serial,
                'qty': qty,
                'operator': operator,
                'notes': notes
            }).execute()
        except Exception as e:
            # 在生产环境中，应该使用更完善的日志系统，而不是只打印到控制台
            print(f"Error logging record: {e}")


    # --- 主程序入口 ---
    if __name__ == '__main__':
        # 启动Flask Web服务器
        # debug=True 会在代码变动后自动重启服务，方便开发，但在生产环境应设为False
        app.run(debug=True, port=5000)
    
