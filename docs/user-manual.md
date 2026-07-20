# Cloud-Lamp — User Manual

Welcome! Your Cloud-Lamp is a small decorative LED lamp that works entirely on its own —
no internet, no app and no account required. If you want more, it also has a built-in
remote control web app for your phone.

> **Permanent address of this manual:**
> `https://github.com/danieldriessen/cloud-lamp/blob/main/docs/user-manual.md`
> (also reachable via the QR code on the sticker on the back of the lamp and the
> book icon in the lamp's web app)

---

## 1. Safety information — please read first

- **Power supply:** use only a regulated **5 V USB power supply (2 A or more)**, such as a
  common phone charger. Never connect the lamp to anything other than 5 V USB.
- **Indoor use only.** Keep the lamp away from water, high humidity (bathrooms), heat
  sources and direct sunlight.
- **Do not cover** the lamp while it is on, and do not operate it inside enclosed
  furniture without airflow. The case must be able to dissipate heat.
- **Not a toy.** The lamp is decoration for a child's room, not a plaything. Install the
  lamp and its cable **out of reach of babies and small children** — the cable is a
  strangulation hazard, and small parts could come loose if the case is damaged.
- **Never leave a damaged lamp powered.** If the case, cable or electronics are visibly
  damaged, unplug it and contact the builder.
- **Do not open the case** while the lamp is plugged in. There are no user-serviceable
  parts inside.
- **Epilepsy note:** some effects produce slow light animation. None of the built-in
  effects flash rapidly, but if flickering light affects you, use the solid colours.
- This lamp is a **hand-built hobby product**, not a certified commercial device. Use it
  with the same care as any small electronic gadget.

---

## 2. What's in the box / on the back

On the **back of the lamp** you'll find a sticker with everything you need:

| Sticker field | Meaning |
|---|---|
| **Setup Wi-Fi** (`Cloud-Lamp-XXXXXX`) | The lamp's own setup hotspot; `XXXXXX` is your lamp's serial |
| **Wi-Fi password** | Password for that setup hotspot |
| **Web address** (`http://cloud-lamp-xxxxxx.local/`) | Your lamp's remote control page (same serial, lowercase) |
| **QR code** | Opens this manual |

---

## 3. Quick start

1. Plug the lamp into a 5 V USB power supply. It is immediately usable with the button —
   Wi-Fi is optional.
2. Press the button once: the lamp turns on.
3. That's it. If you also want phone control, continue with
   [Wi-Fi setup](#5-connecting-the-lamp-to-your-wi-fi).

---

## 4. The button

Everything can be done with the single push-button:

| Action | What it does |
|---|---|
| **Press once** | Turn the lamp on / off |
| **Press twice** (quickly) | Switch to the next effect |
| **Press and hold** | Dim up / down while held (direction alternates each time) |
| **Hold while plugging in power, keep holding ~10 s** | Factory reset — the lamp pulses **red** as a warning; release early to cancel |

The lamp remembers brightness and effect — also after unplugging.

---

## 5. Connecting the lamp to your Wi-Fi

You only need this once (and again if you move or change your Wi-Fi password):

1. Plug the lamp in and wait about a minute.
2. On your phone, open **Settings → Wi-Fi** and connect to the network named
   **`Cloud-Lamp-XXXXXX`** (from the sticker), using the **Wi-Fi password on the sticker**.
3. A configuration page opens automatically (if not, open `192.168.4.1` in your browser).
4. Choose your home Wi-Fi, enter its password, save.
5. The lamp connects to your Wi-Fi. Reconnect your phone to your home Wi-Fi.

The lamp keeps working normally as a lamp during all of this.

---

## 6. The remote control app

Open the **web address from the sticker** (e.g. `http://cloud-lamp-cfb911.local/`) in your
phone's browser — type it exactly, including `http://`. You can:

- turn the lamp on/off and dim it,
- choose colours and special effects from the *Effect Presets* grid,
- pick **any colour you like** — tap *Custom color* and your device's own colour picker
  opens; the lamp remembers the colour even after unplugging (press the button twice to
  go back to the presets),
- adjust the speed of animated effects,
- change settings and install firmware updates.

The app is available in **English, German, Spanish, French, Italian, Dutch, Polish,
Portuguese, Turkish and Russian** (language menu in
Settings).

**iPhone / iPad — install as an app:** the page offers a *"Create a remote control app"*
button with step-by-step instructions. Afterwards the lamp opens full-screen from your
home screen like a normal app.

> **iPhone tip:** if the home-screen icon shows a connection error, open
> **Settings → Apps → Safari** and turn off *"Not Secure Connection Warning"*, then
> remove and re-add the icon. The lamp lives only in your home network and cannot use
> HTTPS — this is normal for home devices.

---

## 7. Firmware updates

The lamp checks for updates automatically (every 6 hours). When one is available, the web
app shows an **Update available** badge under **Settings → Firmware**. Tap
**Install update** and a full-screen guide walks you through installing, restarting and
reconnecting — keep the lamp plugged in and wait until it says **Update complete**. You
can also check manually with **Check for updates now**.

Updates are safe: a failed download or power cut during the update cannot break the lamp,
and all your settings are kept. While the update runs, the lamp may briefly stop answering
the web app (that is normal — it is writing the new firmware and then restarting).

---

## 8. Moving, Wi-Fi change, troubleshooting

**New Wi-Fi / moved house:** the lamp can't find the old network, so it automatically
opens its setup hotspot again after ~1 minute — just repeat
[Wi-Fi setup](#5-connecting-the-lamp-to-your-wi-fi). Alternatively use
**Settings → Change Wi-Fi network…** in the web app.

**Web page not reachable?**

1. Make sure your phone is on the **same Wi-Fi** as the lamp.
2. Type the address exactly as on the sticker, including `http://`.
3. Unplug the lamp, wait 5 seconds, plug it back in, wait a minute.

**Lamp doesn't react to the button?** Unplug and replug the power. The button works even
without any Wi-Fi — if it still doesn't respond, contact the builder.

**Factory reset:** hold the button *while* plugging in the power and keep holding for
about 10 seconds while the lamp pulses red. This erases the saved Wi-Fi and all settings;
afterwards the lamp opens its setup hotspot again (sticker).

---

## 9. Cleaning & care

- Unplug before cleaning.
- Wipe with a **dry or slightly damp** soft cloth. No cleaning agents, no water jets.
- The case is 3D-printed PLA plastic: keep it away from strong heat (radiators, cars in
  summer, > ~50 °C), which can deform it.

---

## 10. Technical data

| | |
|---|---|
| Power supply | 5 V USB, at least 2 A |
| Light source | 24 addressable RGB LEDs (WS2812) |
| Radio | Wi-Fi 2.4 GHz (802.11 b/g/n) — 5 GHz-only networks are not supported |
| Controls | 1 push-button, web app (10 languages) |
| Effects | 18 (solid colours + special effects) plus a free colour picker in the web app |
| Firmware | Open source: `github.com/danieldriessen/cloud-lamp` |

---

*Cloud-Lamp is a personal hobby project by DD Productions. This manual always describes
the latest firmware; the web app's Settings → About shows the version your lamp runs.*
