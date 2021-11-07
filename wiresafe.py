import time
import string
import secrets
import requests
from rich import print
from rich.markup import escape
from rich.console import Console
from paramiko import SSHClient, AutoAddPolicy
from paramiko.ssh_exception import NoValidConnectionsError

console = Console()

def generatePassword(length) -> str:
    return "".join([secrets.choice(string.ascii_letters + string.digits + string.punctuation) for _ in range(length)])


logo = """
$$\      $$\ $$\                      $$$$$$\             $$$$$$\           
$$ | $\  $$ |\__|                    $$  __$$\           $$  __$$\          
$$ |$$$\ $$ |$$\  $$$$$$\   $$$$$$\  $$ /  \__| $$$$$$\  $$ /  \__|$$$$$$\  
$$ $$ $$\$$ |$$ |$$  __$$\ $$  __$$\ \$$$$$$\   \____$$\ $$$$\    $$  __$$\ 
$$$$  _$$$$ |$$ |$$ |  \__|$$$$$$$$ | \____$$\  $$$$$$$ |$$  _|   $$$$$$$$ |
$$$  / \$$$ |$$ |$$ |      $$   ____|$$\   $$ |$$  __$$ |$$ |     $$   ____|
$$  /   \$$ |$$ |$$ |      \$$$$$$$\ \$$$$$$  |\$$$$$$$ |$$ |     \$$$$$$$\ 
\__/     \__|\__|\__|       \_______| \______/  \_______|\__|      \_______|
                                                                            
"""
version = "1.0.0"

console.print(logo, style="magenta")
console.print("Transmit your data safely across the wire at any time, anywhere.", style="italic magenta")

def inquire(question):
    return console.input(f"[green]?[/green] [bold]{question}[/bold] ", password=True)
    
api_key = inquire("Enter your Linode API key")

# print(api_key)

def read_stdout(stdout):
    for line in iter(stdout.readline, ""):
        console.print(line, end="")

class LinodeSession(requests.Session):
    def __init__(self, api_key=None, *args, **kwargs):
        super(LinodeSession, self).__init__(*args, **kwargs)
        self.headers.update({"Authorization": f"Bearer {api_key}"})

    def request(self, method, url, *args, **kwargs):
        return super(LinodeSession, self).request(method, f"https://api.linode.com/v4{url}", *args, **kwargs)

with console.status("Provisioning server...") as status, LinodeSession(api_key=api_key) as ls:
    regions = ls.get("/regions").json()
    region = regions["data"][0]
    console.print("[green]✓[/green] Available regions retrieved")

    linode_types = ls.get("/linode/types").json()
    linode_type = linode_types["data"][0]
    console.print("[green]✓[/green] Linode types retrieved")

    root_pass = generatePassword(12)
    console.print(f"[green]✓[/green] Root password generated: [red]{escape(root_pass)}[/red]")

    linode = ls.post("/linode/instances", json={
        "image": "linode/debian11",
        "region": region["id"],
        "type": linode_type["id"],
        "root_pass": root_pass
    }).json()


    console.print("[green]✓[/green] Creating Linode")

    while (linode_info := ls.get(f"/linode/instances/{linode['id']}").json())["status"] != "running":
        status.update(status=f"{linode_info['status'].capitalize()} server...")
        time.sleep(5)

    server_ip = linode_info["ipv4"][0]

    status.update(status="Connecting to server...")

    ssh = SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    while True:
        try:
            ssh.connect(server_ip, username="root", password=root_pass)
            break
        except NoValidConnectionsError:
            time.sleep(2)
    _, stdout, _ = ssh.exec_command("whoami")
    console.print(f"[green]✓[/green] Logged in as [green]{stdout.read().strip().decode()}[/green]")

    status.update(status="Installing wireguard on the server...")

    # _, stdout, _ = ssh.exec_command("yes | pacman -Syu")
    # read_stdout(stdout)
    _, stdout, _ = ssh.exec_command("apt update && apt install -yy wireguard iptables > /dev/null 2>&1", get_pty=True)
    stdout.channel.recv_exit_status()

    # Server keys
    _, stdout, _ = ssh.exec_command("wg genkey", get_pty=True)
    server_priv = stdout.read().strip().decode()
    console.print(f"[green]✓[/green] Generated server private key: [red]{server_priv}[/red]")
    _, stdout, _ = ssh.exec_command(f"echo {server_priv} | wg pubkey")
    server_pub = stdout.read().strip().decode()
    console.print(f"[green]✓[/green] Generated server public key: [green]{server_pub}[/green]")

    # Client keys
    _, stdout, _ = ssh.exec_command("wg genkey")
    client_priv = stdout.read().strip().decode()
    console.print(f"[green]✓[/green] Generated client private key: [red]{client_priv}[/red]")
    _, stdout, _ = ssh.exec_command(f"echo {client_priv} | wg pubkey")
    client_pub = stdout.read().strip().decode()
    console.print(f"[green]✓[/green] Generated client public key: [green]{client_pub}[/green]")

    ssh.exec_command(f"echo 1 > /proc/sys/net/ipv4/ip_forward")
    console.print("[green]✓[/green] Enable IPv4 forwarding")

    # Write config file
    _, stdout, _ = ssh.exec_command(f"""cat > /etc/wireguard/wg0.conf << 'EOF'
[Interface]
Address = 10.0.0.1/24
SaveConfig = false
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o ens4 -j MASQUERADE; ip6tables -A FORWARD -i %i -j ACCEPT; ip6tables -t nat -A POSTROUTING -o ens4 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o ens4 -j MASQUERADE; ip6tables -D FORWARD -i %i -j ACCEPT; ip6tables -t nat -D POSTROUTING -o ens4 -j MASQUERADE
ListenPort = 443
PrivateKey = {server_priv}

[Peer]
PublicKey = {client_pub}
AllowedIPs = 10.0.0.2/32
EOF""")
    stdout.channel.recv_exit_status()

    console.print("[green]✓[/green] Wireguard configured")
    status.update("Starting wireguard service...")

    _, stdout, _ = ssh.exec_command("systemctl enable wg-quick@wg0 && systemctl start wg-quick@wg0")
    stdout.channel.recv_exit_status()

    status.update("[green]✓[/green] Wireguard services successfully started")

console.print()
console.print(f"""[cyan]Client config:[/cyan]
[Interface]
PrivateKey = {client_priv}
Address = 10.0.0.2/32
DNS = 1.1.1.1, 1.0.0.1
MTU = 1380

[Peer]
PublicKey = {server_pub}
AllowedIPs = 0.0.0.0/0
Endpoint = {server_ip}:443
PersistentKeepalive = 21
""")
