from admin_server import app as admin_flask_app  # reuse existing admin app

# Expose a WSGI application for mounting under /admin
admin_wsgi = admin_flask_app.wsgi_app 