# Capturing your own HTTP traffic

Read this before you start capturing. Most of the questions asked during this
lab turn out to be "why is Wireshark showing me nothing", and the answer is
almost always the interface.

## The loopback problem

Your client and your server are both running on your own machine, so the packets
travel over the loopback interface and never reach your Ethernet or wireless
adapter at all. If you capture on `eth0` or `Wi-Fi` while talking to
`127.0.0.1`, you will see an empty window, and the window is right.

Which interface you want depends on your operating system. On Linux it is `lo`,
and you will want to add yourself to the `wireshark` group so you can capture
without root — `sudo usermod -aG wireshark $USER`, then log out and back in. On
macOS it is `lo0`, which needs the ChmodBPF helper that Wireshark installs; if
`lo0` is greyed out, run the installer again. On Windows you want the adapter
called **Adapter for loopback traffic capture**, which is part of Npcap; if it
is not there, re-run the Npcap installer and tick *Support loopback traffic*.
Older builds call the same thing *Npcap Loopback Adapter*.

If loopback capture simply refuses to work, use two machines on a network you
own: run the server with `--host 0.0.0.0` on one, point the client at its
address from the other, and capture on the real network card. That is the better
capture anyway, for reasons set out at the end of this document.

## How to do it

Start your server, then open Wireshark and select the loopback interface. Before
you start capturing, set a capture filter so the file stays small:

```
tcp port 8080
```

A word about the two kinds of filter, because mixing them up is a rite of
passage. **Capture filters** use the syntax above and throw everything else away
as it arrives, so what they discard is gone for good. **Display filters** use
Wireshark's own syntax, which for the same thing would be `tcp.port == 8080`,
and merely hide packets you have already captured. They go in different boxes
and they are not interchangeable.

Now start capturing and run exactly one request:

```bash
python3 client.py --path '/echo?name=ada&unit=7'
```

Stop the capture. You should see somewhere around nine packets: three for the
handshake, one carrying your request, an acknowledgement, one carrying the
response, and three or four closing the connection down. Then start a fresh
capture and do the same thing with a `POST`.

Save the result with **File → Save As** as `capture.pcapng`, and hand in the
file itself rather than only screenshots, because we open it.

Both exchanges can live in one file as long as you say in your screenshot
captions which packet numbers belong to which.

## Display filters worth knowing

```
tcp.port == 8080                      everything on our port
http                                  only what the HTTP dissector recognised
http.request                          requests only
http.response                         responses only
http.request.method == "POST"         just the POST
http.response.code == 404             your 404 path, once you have one
urlencoded-form                       form fields, dissected one per line
tcp.flags.syn == 1 && tcp.flags.ack == 0   the opening SYN
tcp.flags.fin == 1                    the connection closing
frame contains "COM2512"              brute force: find your own payload
```

## Reading a request

Click the packet carrying your `GET` and expand the layers in the detail pane.
You are looking at the protocol stack from the outside inwards.

At the top is the frame itself, which is capture metadata — a timestamp and a
length. Below that is the link layer, and here it is worth pausing: on Linux
loopback this header is synthesised with all-zero MAC addresses, and on macOS it
is a four-byte null header. There is no real Ethernet involved. The layer you
are being shown does not exist.

Then comes IP, with source and destination both `127.0.0.1`; then TCP, with the
ports, sequence numbers, flags and window; and finally HTTP, where you will find
your request line and each header dissected into its own field, and, for the
`POST`, the body — shown as line-based text data for `text/plain`, or broken out
field by field if you sent a form. The bottom pane shows the same bytes as hex
and ASCII, and the fact that you can read them there at all is exactly because
HTTP is a text protocol.

Then right-click and choose **Follow → TCP Stream**. Request and response appear
together as one conversation, your side in one colour and the server's in
another, with the carriage returns rendered as line breaks. That is the view to
screenshot. **Follow → HTTP Stream** does the same thing with the TCP
bookkeeping stripped out.

## When HTTP is not dissected

Port 8080 is in Wireshark's default list of HTTP ports, so this usually just
works. When it does not, right-click the packet, choose **Decode As**, and set
TCP port 8080 to HTTP.

Failing that, check you clicked a packet that has a payload: a bare SYN or
acknowledgement contains no HTTP, and nothing is wrong. If you see
`[TCP segment of a reassembled PDU]` everywhere, that is also normal — the
message spans several segments and Wireshark shows the assembled version on the
last one.

You may also see packets marked in red or black complaining about bad checksums.
That is an artefact of loopback: checksums are offloaded or skipped altogether,
because nothing can corrupt a packet that never leaves the kernel. If the noise
bothers you, untick *Validate the TCP checksum if possible* under **Edit →
Preferences → Protocols → TCP**.

## What loopback distorts

If you captured on loopback, three of the things you are looking at are not
representative of a real network, and it is worth knowing which.

Segment sizes are wrong: loopback has a maximum packet size of around 65 KB
rather than Ethernet's 1500, so your request and response each fit comfortably
in one segment where on a real link a large response would be split across many.
Any overhead ratio you calculate here flatters HTTP considerably.

Timing is meaningless, because the round trip is measured in microseconds. Any
conclusion about latency, or about how much a persistent connection saves you,
is worthless on loopback.

And there is no loss and no reordering, so you will never see a retransmission,
and therefore never see TCP recover from one.

## tshark, if you prefer the terminal

```bash
# capture to a file
tshark -i lo -f 'tcp port 8080' -w capture.pcapng

# watch HTTP requests go past, one line each
tshark -i lo -f 'tcp port 8080' -Y http -T fields \
       -e frame.number -e http.request.method -e http.request.uri -e http.response.code

# read a saved file and print the full HTTP tree
tshark -r capture.pcapng -Y http -V
```

The files are the same either way, so capturing with `tshark` and then reading
the result in the Wireshark window is perfectly reasonable if that suits you
better.

## Capture only your own traffic

Capture on loopback, or on a network you own or have been given permission to
test. Do not capture on campus wireless, a shared lab segment, a café, or
anywhere else you might collect traffic belonging to other people. On most
networks that is a disciplinary matter, and in many places it is a criminal
offence, regardless of whether you ever look at what you collected. The entire
exercise works on `127.0.0.1`, where the only traffic is yours.
