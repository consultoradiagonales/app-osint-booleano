import os, sys, smtplib, keyring
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

print("=== TEST EMAIL RASTREADOR OSINT-BOOLEANO ===")
print()

target = "RastreadorOSINTBooleanoSMTP"
host = "smtp.gmail.com"
port = 587
user = "Fernandogenazzini@gmail.com"
to = "Fernandogenazzini@gmail.com"

print(f"Buscando credencial en Windows Credential Manager...")
password = keyring.get_password(target, user)

if not password:
    print("ERROR: Credencial NO encontrada.")
    print("Ejecuta configurar_email_auto.bat e ingresa la clave de aplicacion de Gmail.")
    input("Presiona Enter para cerrar...")
    sys.exit(1)

print("Credencial encontrada. OK")
print()
print(f"Conectando a {host}:{port}...")

try:
    server = smtplib.SMTP(host, port, timeout=15)
    server.ehlo()
    server.starttls()
    server.ehlo()
    print("Conexion STARTTLS: OK")
    print(f"Autenticando como {user}...")
    server.login(user, password)
    print("Autenticacion: OK")
    print()
    print(f"Enviando email de prueba a {to}...")
    msg = MIMEMultipart()
    msg['From'] = user
    msg['To'] = to
    msg['Subject'] = "TEST - Rastreador OSINT-BOOLEANO funcionando"
    msg.attach(MIMEText("Email de prueba del Rastreador OSINT-BOOLEANO. Si lo recibis, el email esta configurado correctamente.", 'plain'))
    server.sendmail(user, to, msg.as_string())
    server.quit()
    print()
    print("=== EXITO: Email enviado! ===")
    print(f"Revisa tu Gmail: {to}")
except Exception as e:
    print(f"ERROR: {e}")

print()
input("Presiona Enter para cerrar...")