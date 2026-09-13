"""页面路由。"""

from flask import render_template

from app_common import admin_required, login_required


def register_page_routes(app):
    # ==================== 页面路由 ====================

    @app.route('/')
    @login_required
    def index():
        """主页。"""
        return render_template('index.html')


    @app.route('/admin')
    @admin_required
    def admin_page():
        """管理员后台页面。"""
        return render_template('admin.html')


    @app.route('/change-password')
    @login_required
    def change_password_page():
        """修改密码页面：用户验证旧密码后设置新密码。"""
        return render_template('change_password.html')


    @app.route('/recycle-bin')
    @login_required
    def recycle_bin_page():
        """回收站页面：查看、恢复已删除的员工记录。"""
        return render_template('recycle_bin.html')


    @app.route('/backup')
    @admin_required
    def backup_page():
        """管理员数据库备份页面：手动创建、查看和下载备份。"""
        return render_template('backup.html')
