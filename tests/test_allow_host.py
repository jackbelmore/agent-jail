"""--allow-host: the proxy's decisions, and that the jail has no other way out.
Design: docs/ALLOW_HOST.md."""

import os
import re

import pytest
from conftest import JAIL

# A raw CONNECT through the forwarder, printing the proxy's status code.
ASK = """
import socket, sys
s = socket.create_connection(("127.0.0.1", 3128), timeout=10)
s.sendall(f"{sys.argv[1]} {sys.argv[2]} HTTP/1.1\\r\\nHost: {sys.argv[2]}\\r\\n\\r\\n".encode())
print(sys.argv[2], s.recv(200).split()[1].decode())
"""


def ask(jail, requests, *hosts):
    """Send each (method, target) to the proxy; return {target: status}."""
    lines = "; ".join(f"python3 -I -c '{ASK}' {m} '{t}'" for m, t in requests)
    opts = [a for h in hosts for a in ("--allow-host", h)]
    r = jail.run(*opts, "shell", "-c", lines, net="")
    return dict(line.split() for line in r.stdout.splitlines()), r


def proxy_module():
    """The proxy's code from bin/agent-jail, loaded without starting it."""
    code = re.search(r"proxy_py\(\) \{\n    cat <<'EOF'\n(.*?)\nEOF", JAIL.read_text(), re.S)
    ns = {"__name__": "agent_jail_proxy"}
    exec(code.group(1), ns)  # noqa: S102 - our own code, as the shell would run it
    return ns


@pytest.mark.parametrize("addr, public", [
    ("93.184.215.14", True), ("2606:4700::1111", True),
    ("127.0.0.1", False), ("10.1.2.3", False), ("192.168.1.1", False),
    ("100.100.100.100", False), ("169.254.169.254", False), ("::1", False),
    ("fd00::1", False), ("fe80::1%2", False), ("224.0.0.1", False),
    ("::ffff:127.0.0.1", False), ("64:ff9b::7f00:1", False), ("2002:7f00:1::", False),
    ("64:ff9b::808:808", True),
])
def test_proxy_knows_public_addresses(addr, public):
    assert proxy_module()["public"](addr) is public


def test_proxy_matches_names_and_ports():
    proxy = proxy_module()
    proxy["RULES"][:] = [("*.example.com", 443), ("api.example.org", 8443)]
    listed = proxy["listed"]
    assert listed("www.example.com", 443) and listed("a.b.example.com", 443)
    assert not listed("example.com", 443)          # *. doesn't include the name itself
    assert not listed("badexample.com", 443)
    assert not listed("www.example.com", 80)
    assert listed("api.example.org", 8443) and not listed("api.example.org", 443)


def test_proxy_decides_by_list_port_and_address(jail):
    # .invalid and .test never resolve (RFC 6761): 502 means "on the list, then looked up".
    seen, r = ask(jail, [
        ("CONNECT", "a.b.invalid:443"), ("CONNECT", "invalid:443"),
        ("CONNECT", "exact.test:8443"), ("CONNECT", "exact.test:443"),
        ("CONNECT", "other.test:443"), ("CONNECT", "1.2.3.4:443"),
        ("CONNECT", "[::1]:443"), ("CONNECT", "localhost:443"),
        ("GET", "http://a.invalid/"),
    ], "*.invalid", "exact.test:8443", "localhost")
    assert seen == {
        "a.b.invalid:443": "502", "invalid:443": "403",
        "exact.test:8443": "502", "exact.test:443": "403",   # only the listed port
        "other.test:443": "403", "1.2.3.4:443": "403", "[::1]:443": "403",
        "localhost:443": "403",         # listed, but it resolves to loopback
        "http://a.invalid/": "405",     # only CONNECT
    }, r.stderr
    # What was refused, and why, is listed after the run.
    assert "the --allow-host proxy refused:" in r.stderr
    assert "localhost:443 resolves to a non-public address" in r.stderr
    assert "other.test:443 not on the --allow-host list" in r.stderr


def test_allow_host_leaves_no_other_way_out(jail, host_tcp_server):
    code = ("import socket, sys\n"
            "for host, port in [('1.1.1.1', 443), ('127.0.0.1', int(sys.argv[1]))]:\n"
            "    try:\n"
            "        socket.create_connection((host, port), timeout=3); print('OPEN')\n"
            "    except OSError as e:\n"
            "        print(type(e).__name__)\n"
            "try:\n"
            "    socket.getaddrinfo('example.com', 443); print('DNS')\n"
            "except OSError:\n"
            "    print('NODNS')\n")
    r = jail.run("--allow-host", "example.com", "shell", "-c",
                 f"python3 -I -c \"{code}\" {host_tcp_server}", net="")
    # No route out, the host's loopback isn't the jail's, and no resolver.
    assert r.stdout.split() == ["OSError", "ConnectionRefusedError", "NODNS"], r.stderr


@pytest.mark.skipif(os.environ.get("AGENT_JAIL_OFFLINE") == "1", reason="offline")
def test_allow_host_reaches_listed_names_only(jail):
    fetch = ("import sys, urllib.request\n"
             "try:\n"
             "    print(urllib.request.urlopen(sys.argv[1], timeout=15).status)\n"
             "except OSError as e:\n"
             "    print('refused', e)\n")
    r = jail.run("--allow-host", "example.com", "shell", "-c",
                 f"for u in https://example.com https://example.org; do "
                 f"python3 -I -c \"{fetch}\" $u; done", net="")
    lines = r.stdout.splitlines()
    assert lines[0] == "200", r.stderr
    assert lines[1].startswith("refused") and "403" in lines[1]


@pytest.mark.parametrize("args, error", [
    (["--net", "none", "--allow-host", "example.com"], "needs --net isolated"),
    (["--allow-host", "example.com", "--host-port", "11434"], "can't be used together"),
    (["--allow-host", "1.2.3.4"], "bad --allow-host"),
    (["--allow-host", "exa mple.com"], "bad --allow-host"),
    (["--allow-host", "example.com:99999"], "bad --allow-host"),
])
def test_allow_host_arguments(jail, args, error):
    r = jail.run(*args, "shell", "-c", "true", net="")
    assert r.returncode != 0 and error in r.stderr


def test_project_file_narrows_the_allowlist(jail):
    (jail.work / ".agent-jail").write_text("allow-host = b.invalid\nallow-host = c.invalid\n")
    # No list of yours: the project's applies.
    seen, r = ask(jail, [("CONNECT", "b.invalid:443"), ("CONNECT", "d.invalid:443")])
    assert seen == {"b.invalid:443": "502", "d.invalid:443": "403"}, r.stderr
    assert "allow-host b.invalid:443 c.invalid:443" in r.stderr
    # A list of yours: only hosts on both.
    seen, r = ask(jail, [("CONNECT", "a.invalid:443"), ("CONNECT", "b.invalid:443"),
                         ("CONNECT", "c.invalid:443")], "a.invalid", "b.invalid")
    assert seen == {"a.invalid:443": "403", "b.invalid:443": "502", "c.invalid:443": "403"}




def test_ctrl_c_in_the_jail_leaves_the_proxy_running(jail):
    # Interrupting a command in the jail's shell (or a key press in an agent's
    # raw-mode terminal) must not take the proxy or the forwarder with it.
    from test_jail import pty_run
    probe = ("python3 -I -c 'import socket; s = socket.create_connection((\"127.0.0.1\", 3128));"
             " s.sendall(b\"CONNECT x.invalid:443 HTTP/1.1\\r\\n\\r\\n\");"
             " print(\"status\", s.recv(64).split()[1].decode())'\r")
    status, out = pty_run(jail, ["sleep 30\r", "\x03", probe, "exit\r"],
                          "--allow-host", "x.invalid", "shell")
    assert "status 502" in out
