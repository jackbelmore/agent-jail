# `--allow-host`: a domain allowlist

By default the jail reaches every public address. That stops it reaching your
machine and your network, but not sending what it reads to any server on the
internet. `--allow-host` narrows the network to the names you list:

```console
$ agent-jail --allow-host api.anthropic.com --allow-host '*.github.com' claude
```

This is the design.

## How it works

```
 jail (own network namespace, loopback only)          host
 ┌──────────────────────────────────────────┐        ┌──────────────────────────┐
 │ agent ── HTTPS_PROXY=127.0.0.1:3128      │        │ agent-jail's proxy       │
 │            │                             │  Unix  │  · CONNECT only          │
 │            ▼                             │ socket │  · name on the list?     │
 │ forwarder 127.0.0.1:3128 ────────────────┼────────┼▶ · resolve on the host   │
 │                                          │        │  · every address public? │
 └──────────────────────────────────────────┘        │  · connect to that one ──┼─▶ internet
                                                     └──────────────────────────┘
```

1. **No route out.** With an allowlist the jail gets bubblewrap's own network
   namespace and no pasta: it has a loopback interface and nothing else. A
   program that ignores the proxy settings simply can't connect, and nothing
   inside can send DNS queries to the outside.
2. **One way through: a Unix socket.** `agent-jail` starts a small proxy on the
   host that listens on a Unix socket in its private temporary directory (mode
   0700), and binds that socket into the jail. There is no TCP listener on the
   host for other local processes, or other jails, to reach.
3. **A forwarder inside.** Most programs speak to an HTTP proxy over TCP, not a
   Unix socket, so a forwarder in the jail listens on `127.0.0.1:3128` and
   copies each connection to the socket. `HTTPS_PROXY`, `HTTP_PROXY`,
   `ALL_PROXY` (and lowercase forms) point at it, `NO_PROXY` covers loopback, and
   `NODE_USE_ENV_PROXY=1` makes Node's built-in `fetch` use it. The forwarder
   has no say over what is allowed: a process that talks to the socket directly
   gets the same answers.
4. **The proxy decides.** It accepts only `CONNECT host:port`, which is how
   clients reach `https://` URLs through a proxy. For each request:
   - the name must be on the list, and the port must be 443 or the one listed
     (`host:port`); `*.example.com` matches any name under `example.com` but not
     `example.com` itself;
   - IP addresses are refused, only names are allowed;
   - the name is resolved **on the host**, once, and if **any** address it
     resolves to isn't a public one, the request is refused. Loopback, private
     ranges, CGNAT (Tailscale), link-local (cloud metadata), multicast and
     reserved ranges all count, and so do IPv4 addresses inside IPv4-mapped,
     NAT64 (`64:ff9b::/96`) and 6to4 IPv6 addresses;
   - it then connects to an address it checked, not to the name again, so a
     second DNS answer can't swap in a private address (DNS rebinding).
5. **You see what was refused.** After the run, `agent-jail` lists the names
   the proxy turned away, so you can add the ones you want.

Both the proxy and the forwarder are short Python 3 programs, using only the
standard library, embedded in `bin/agent-jail`. So `--allow-host` needs
`python3` on the host (it is in `/usr`, so the jail has it too) and no other
package, build step or binary.

## What it is good for, and what it isn't

Good for: making exfiltration need a host you allowed, keeping the agent off
everything that isn't HTTPS, and stopping DNS tunnelling, since the jail has
no resolver.

Not a guarantee that data stays with the hosts you meant:

- **Broad names are broad.** Allowing `github.com` allows gists, issues and
  every repository on it. `*.amazonaws.com` or `*.googleapis.com` cover
  millions of customers' endpoints.
- **Domain fronting.** The proxy sees the name in `CONNECT`, not what is inside
  the TLS connection. A CDN that routes on the inner `Host` header can carry
  the request to another of its customers.
- **Only HTTPS.** `http://` URLs, `git@github.com:` (SSH) and other protocols
  don't go through the proxy, and fail. Use `https://` remotes.
- **Your own public addresses.** A name you allow that resolves to a public
  address of your own machine or network reaches it.

## Options

- `--allow-host NAME`, repeatable. `NAME` is `example.com`, `*.example.com`,
  or either with `:PORT`. In the config file, `allow-host = NAME`.
- It needs `--net isolated` (the default) and replaces it; `--host-port` can't
  be used with it, because there is no pasta to forward ports.
- A project's `.agent-jail` can use `allow-host` too, but only to narrow: if
  you haven't listed hosts, its list applies; if you have, only hosts on both
  lists do.
