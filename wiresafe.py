import time
import string
import secrets
import requests
from rich import print
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
    console.print(f"[green]✓[/green] Root password generated: [red]{root_pass}[/red]")

    linode = ls.post("/linode/instances", json={
        "image": "linode/arch",
        "region": region["id"],
        "type": linode_type["id"],
        "root_pass": root_pass
    }).json()


    console.print("[green]✓[/green] Creating Linode")

    while (linode_info := ls.get(f"/linode/instances/{linode['id']}").json())["status"] != "running":
        status.update(status=f"{linode_info['status'].capitalize()} server...")
        time.sleep(5)

    status.update(status="Connecting to server...")

    ssh = SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    while True:
        try:
            ssh.connect(linode_info["ipv4"][0], username="root", password=root_pass)
            break
        except NoValidConnectionsError:
            time.sleep(2)
    _, stdout, _ = ssh.exec_command("whoami")
    console.print(f"[green]✓[/green] Logged in as {stdout.read().strip().decode()}")
