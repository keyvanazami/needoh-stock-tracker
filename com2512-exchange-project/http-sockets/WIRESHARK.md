# Capturing your own HTTP traffic

Read this before you start. The first half of the lab's support questions are always
"why is Wireshark showing me nothing", and the answer is nearly always the interface.

## The loopback trap

Your client and server are both on your own machine, so the packets travel over the
**loopback** interface and never reach your Ethernet or Wi-Fi adapter. Capturing on
`eth0` / `Wi-Fi` while talking to `127.0.0.1` shows you an empty window, correctly.

Pick the right interface for your OS:

| OS | interface to select | notes |
|---|---|---|
| Linux | `lo` | add yourself to the `wireshark` group to capture without root: `sudo usermod -aG wireshark $USER`, then log out and back in |
| macOS | `lo0` | needs the ChmodBPF helper that Wireshark installs; re-run the installer if `lo0` is greyed out |
| Windows | **Adapter for loopback traffic capture** | an Npcap feature. If absent, re-run the Npcap installer and tick *Support loopback traffic*. Older builds call it *Npcap Loopback Adapter* |

If loopback capture simply will not work, use two machines on a link you own: run
`server.py --host 0.0.0.0` on one, point `client.py --host <server-ip>` from the other,
and capture on the real NIC. This is the better capture anyway — see
[What loopback distorts](#what-loopback-distorts).

## Procedure

1. Start the server: `python3 server.py`
2. In Wireshark, select the loopback interface. Before clicking the shark fin, set a
   **capture filter** so the file stays small:

   ```
   tcp port 8080
   ```

   Capture filters use BPF syntax (`tcp port 8080`) and discard everything else at
   capture time. **Display filters** use Wireshark's own syntax (`tcp.port == 8080`)
   and only hide packets you already captured. They are not interchangeable, and
   typing one into the other's box is a rite of passage.
3. Start capturing. Run exactly one request:

   ```bash
   python3 client.py --path '/echo?name=ada&unit=7'
   ```
4. Stop capturing. You should see roughly nine packets: three for the handshake, one
   carrying the request, an ACK, one carrying the response, and three or four for the
   teardown.
5. Start a fresh capture and repeat with the POST:

   ```bash
   python3 client.py -X POST --data 'hello from COM2512' --path /echo
   ```
6. **File → Save As →** `capture.pcapng`. Submit the file, not just screenshots.

Both exchanges may live in one file; say in your report which packet numbers belong to
which.

## Display filters worth knowing

```
tcp.port == 8080                      everything on our port
http                                  only packets the HTTP dissector recognised
http.request                          requests only
http.response                         responses only
http.request.method == "POST"         just the POST
http.request.method == "GET"          just the GET
http.response.code == 404             your 404 path, once you have one
urlencoded-form                       form fields, dissected one per line
tcp.flags.syn == 1 && tcp.flags.ack == 0   the opening SYN
tcp.flags.fin == 1                    teardown
frame contains "COM2512"              brute force: find your own payload
```

## Reading one request

Click the packet carrying your GET and expand the layers in the detail pane. You are
looking at the protocol stack from the outside in:

- **Frame** — capture metadata: timestamp, captured length
- **Ethernet / Loopback** — on Linux `lo` this header is synthesised with all-zero MAC
  addresses; on macOS `lo0` it is a 4-byte NULL header. There is no real Ethernet here.
  Worth noticing: the link layer you are told about does not exist
- **Internet Protocol** — source and destination `127.0.0.1`
- **Transmission Control Protocol** — ports, sequence numbers, flags, window
- **Hypertext Transfer Protocol** — your request line and headers, field by field

Expand the HTTP layer and find, as separate dissected fields: the request method, the
request URI, the version, each header, and — for the POST — the body, shown as
*Line-based text data* for `text/plain` or *HTML Form URL Encoded* for a form. The
bottom pane shows the same bytes in hex and ASCII; HTTP being ASCII is why it is
readable there at all.

Then **right-click → Follow → TCP Stream**. Request and response appear as one
conversation, your side in red, the server's in blue, CRLFs rendered as line breaks.
This is the view to screenshot for your report. **Follow → HTTP Stream** does the same
with the TCP bookkeeping stripped out.

## If HTTP is not dissected

Port 8080 is in Wireshark's default HTTP port list, so dissection normally just
happens. When it does not:

- **Right-click the packet → Decode As… → TCP port 8080 → HTTP**, then OK.
- Check you clicked a packet with a payload. A bare SYN or ACK has no HTTP in it —
  nothing is wrong.
- `[TCP segment of a reassembled PDU]` means the message spans segments. Wireshark
  shows the assembled HTTP on the *last* segment of the group. This is normal.
- Red or black packets complaining about a bad checksum are a loopback artefact:
  checksums are offloaded or skipped because nothing can corrupt a packet that never
  leaves the kernel. Untick *Validate the TCP checksum if possible* under
  **Edit → Preferences → Protocols → TCP** if the noise bothers you.

## What loopback distorts

Say so in your report if you captured on loopback — three of your measurements are
affected:

- **Segment sizes.** Loopback MTU is around 65 KB, not Ethernet's 1500. Your request
  and response each fit in one segment where on a real link a large response would be
  split across many. Overhead ratios computed here are flattering.
- **Timing.** RTT is microseconds. Any conclusion about latency, keep-alive benefit, or
  congestion is meaningless on loopback.
- **Reliability.** Zero loss, zero reordering. You will never see a retransmission, so
  you will never see TCP recover from one.

## tshark, if you prefer a terminal

```bash
# capture to a file
tshark -i lo -f 'tcp port 8080' -w capture.pcapng

# watch HTTP requests go past, one line each
tshark -i lo -f 'tcp port 8080' -Y http -T fields \
       -e frame.number -e http.request.method -e http.request.uri -e http.response.code

# read a saved file and print the full HTTP tree
tshark -r capture.pcapng -Y http -V
```

The same files open in the Wireshark GUI, so capture with `tshark` and read in the GUI
if that suits you better.

## Capture only your own traffic

Capture on loopback, or on a network you own or are authorised to test. Do not capture
on campus Wi-Fi, a shared lab segment, a café, or anywhere you might collect other
people's traffic — on most networks that is a disciplinary matter and in many places it
is an offence, regardless of whether you look at what you collected. The whole lab
works on `127.0.0.1`, where the only traffic is yours.
