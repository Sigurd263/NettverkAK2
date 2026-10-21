#!/usr/bin/env python3
"""Sett opp SSH på en Cisco IOS-ruter eller -svitsj via konsoll."""

import time
import re
from ipaddress import IPv4Interface, IPv4Address
from getpass import getpass

import serial


def send(konsoll, kommando="", ventetid=1, skjul=False):
    konsoll.write((kommando + "\r").encode())
    time.sleep(ventetid)
    svar = konsoll.read(konsoll.in_waiting).decode(errors="ignore")
    if not skjul:
        print(svar, end="", flush=True)
    return svar


def klargjor(konsoll, passord):
    # Vent på oppstart og avslå veiviseren for førstegangsoppsett.
    for _ in range(60):
        svar = send(konsoll, ventetid=2).strip()
        if "initial configuration dialog" in svar.lower():
            send(konsoll, "no", 10)
        elif "terminate autoinstall" in svar.lower():
            send(konsoll, "yes", 5)
        elif "(config" in svar:
            send(konsoll, "end")
        elif svar.endswith((">", "#")):
            break
    else:
        raise RuntimeError("Ingen ledetekst. Kontroller kabel og konsolltilkobling.")

    svar = send(konsoll, "enable")
    if "password:" in svar.lower():
        svar = send(konsoll, passord, skjul=True)
    if not svar.strip().endswith("#"):
        raise RuntimeError("Kunne ikke åpne enable-modus. Kontroller passordet.")
    send(konsoll, "terminal length 0")


def har_ledetekst(svar, modus="config"):
    """Finn ledeteksten også når IOS skriver loggmeldinger etter den."""
    return f"({modus})#" in svar


def sett_opp_vty(konsoll):
    """Sett lokal SSH-innlogging etter å ha bekreftet VTY-modus."""
    svar = send(konsoll, "line vty 0 15")
    if any(feil in svar.lower() for feil in ("invalid", "out of range")):
        svar = konfigurer(konsoll, "line vty 0 4")
    # Konsollmeldinger kan komme forsinket eller deles mellom lesinger.
    for _ in range(3):
        if har_ledetekst(svar, "config-line"):
            break
        svar += send(konsoll, ventetid=2)
    if not har_ledetekst(svar, "config-line"):
        raise RuntimeError("Kunne ikke bekrefte VTY-modus etter tre nye avlesninger.")
    for kommando in ["login local", "transport input ssh", "exit", "end"]:
        konfigurer(konsoll, kommando)


def konfigurer(konsoll, kommando, skjul=False, alternativ=None):
    svar = send(konsoll, kommando, skjul=skjul)
    # Faste L2-porter trenger ikke (og støtter ikke alltid) «switchport» alene.
    # Gjør først om porten når IOS uttrykkelig sier at den er rutet.
    if kommando in ("switchport mode access", "switchport mode trunk") and "not a switching port" in svar.lower():
        konfigurer(konsoll, "switchport")
        svar = send(konsoll, kommando, skjul=skjul)
    # IOS-varianter bruker enten mellomrom eller bindestrek i domenekommandoer.
    # Prøv alternativet bare når enheten avviser syntaksen.
    syntaksfeil = ("invalid input", "incomplete command", "ambiguous command")
    if alternativ and any(tekst in svar.lower() for tekst in syntaksfeil):
        print(f"\nPrøver alternativ IOS-syntaks: {alternativ}")
        kommando = alternativ
        svar = send(konsoll, kommando, skjul=skjul)
    feil = ("invalid input", "incomplete command", "ambiguous command", "error",
            "too short", "minimum length", "password rejected", "not allowed",
            "command rejected", "not a switching port")
    if any(tekst in svar.lower() for tekst in feil):
        navn = "passordkommando" if skjul else kommando
        raise RuntimeError(f"Enheten avviste: {navn}")
    return svar


def lag_ssh_nokler(konsoll):
    """Håndter både direkte og interaktiv RSA-generering i Cisco IOS."""
    svar = send(konsoll, "crypto key generate rsa modulus 2048", 3)
    if "invalid input" in svar.lower():
        svar = send(konsoll, "crypto key generate rsa", 3)
    for _ in range(30):
        tekst = svar.lower()
        if any(feil in tekst for feil in ("invalid input", "incomplete command", "error", "failed")):
            raise RuntimeError("Kunne ikke lage RSA-nøkler. Kontroller IOS-støtte for SSH.")
        if "[yes/no]" in tekst:
            # Behold eksisterende nøkler for å unngå endret SSH-vertsnøkkel.
            svar = send(konsoll, "no", 2)
        elif "how many bits" in tekst:
            svar = send(konsoll, "2048", 3)
        elif har_ledetekst(svar):
            return
        else:
            time.sleep(2)
            # Behold tidligere tekst dersom ledeteksten kommer i flere biter.
            nytt_svar = konsoll.read(konsoll.in_waiting).decode(errors="ignore")
            svar += nytt_svar
            print(nytt_svar, end="", flush=True)
    raise RuntimeError("RSA-genereringen ble ikke ferdig. Kontroller konsollen.")


def portkonflikter(accessporter, trunkporter):
    """Oppdag også at Fa0/1 og FastEthernet0/1 er samme port."""
    def normaliser(port):
        port = port.strip().lower()
        match = re.fullmatch(r"([a-z]+)([0-9]+(?:/[0-9]+)*)", port)
        if not match:
            return port
        navn, nummer = match.groups()
        for fullt_navn in ("fastethernet", "gigabitethernet", "tengigabitethernet", "ethernet"):
            if fullt_navn.startswith(navn):
                return fullt_navn + nummer
        return port
    return ({normaliser(p) for p in accessporter if p.strip()}
            & {normaliser(p) for p in trunkporter if p.strip()})


def hovedprogram():
    print("Sett opp SSH på Cisco-ruter eller -svitsj — versjon 6\n")
    print("1: Ruter\n2: L2-svitsj\n3: L3-svitsj (med ruting)")
    enhetstype = input("Velg enhetstype [1/2/3]: ").strip()
    if enhetstype not in ("1", "2", "3"):
        raise ValueError("Velg 1, 2 eller 3.")
    er_svitsj = enhetstype in ("2", "3")
    ruting = enhetstype in ("1", "3")
    port = input("Konsollport [/dev/ttyUSB0]: ").strip() or "/dev/ttyUSB0"
    gammelt_passord = getpass("Nåværende enable-passord (tomt hvis ingen): ")
    nytt_passord = getpass("Nytt enable-passord: ")
    brukernavn = input("SSH-brukernavn: ").strip()
    ssh_passord = getpass("SSH-passord: ")
    vertsnavn = input("Navn på enheten: ").strip()
    domene = input("Domenenavn: ").strip()
    if not all((nytt_passord, brukernavn, ssh_passord, vertsnavn, domene)):
        raise ValueError("Navn, domene og nye passord må fylles ut.")

    with serial.Serial(port, baudrate=9600, timeout=1) as konsoll:
        klargjor(konsoll, gammelt_passord)
        send(konsoll, "show ip interface brief", 3)

        eksempel = "Vlan10" if er_svitsj else "GigabitEthernet0/0"
        grensesnitt = input(f"Grensesnitt for IP, f.eks. {eksempel}: ").strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9/.-]*", grensesnitt):
            raise ValueError("Skriv ett gyldig grensesnittnavn fra oversikten.")
        if enhetstype == "2" and not grensesnitt.lower().startswith("vlan"):
            raise ValueError("L2-svitsjer skal ha administrasjonsadressen på et VLAN.")
        if not er_svitsj and grensesnitt.lower().startswith("vlan"):
            raise ValueError("Velg et rutet grensesnitt på ruteren, f.eks. Gi0/0.")
        ip_adresse = input("IP-adresse: ").strip()
        nettmaske = input("Nettmaske: ").strip()
        gateway = input("Standard gateway (valgfritt): ").strip()
        # Kontroller IPv4-adresse og maske før konfigurasjonen endres.
        adresse = IPv4Interface(f"{ip_adresse}/{nettmaske}")
        nettmaske = str(adresse.netmask)
        if gateway:
            IPv4Address(gateway)

        vlan = ""
        accessporter = []
        trunkporter = []
        if grensesnitt.lower().startswith("vlan"):
            vlan = grensesnitt[4:].strip()
            if not vlan.isdigit() or not 1 <= int(vlan) <= 4094:
                raise ValueError("VLAN må være et tall mellom 1 og 4094.")
            grensesnitt = f"Vlan{vlan}"
            print("En port skal stå enten som access eller trunk, ikke begge deler.")
            while True:
                accessporter = input("Accessporter, f.eks. Fa0/1,Gi0/1 (valgfritt): ").split(",")
                trunkporter = input("Trunkporter, f.eks. Gi0/2 (valgfritt): ").split(",")
                if portkonflikter(accessporter, trunkporter):
                    print("Samme port er oppgitt som access og trunk. Skriv portlistene på nytt.")
                    continue
                break

        kommandoer = [
            "configure terminal",
            f"hostname {vertsnavn}",
        ]
        for kommando in kommandoer:
            konfigurer(konsoll, kommando)
        konfigurer(konsoll, "no ip domain lookup", alternativ="no ip domain-lookup")
        konfigurer(konsoll, f"ip domain name {domene}",
                   alternativ=f"ip domain-name {domene}")
        konfigurer(konsoll, f"enable secret {nytt_passord}", skjul=True)
        konfigurer(konsoll, f"username {brukernavn} privilege 15 secret {ssh_passord}", skjul=True)

        kommandoer = []
        # Sett portmodus; rutede porter konverteres ved behov i konfigurer().
        if vlan:
            kommandoer += [f"vlan {vlan}", "exit"]
            for portnavn in accessporter:
                if portnavn.strip():
                    kommandoer += [
                        f"interface {portnavn.strip()}", "switchport mode access",
                        f"switchport access vlan {vlan}", "no shutdown", "exit",
                    ]
            for portnavn in trunkporter:
                if portnavn.strip():
                    kommandoer += [
                        f"interface {portnavn.strip()}", "switchport mode trunk",
                        f"switchport trunk allowed vlan add {vlan}", "no shutdown", "exit",
                    ]

        kommandoer.append(f"interface {grensesnitt}")
        # Bare L3-svitsjer trenger å gjøre en fysisk port om til rutet port.
        if enhetstype == "3" and not grensesnitt.lower().startswith(("vlan", "loopback")):
            kommandoer.append("no switchport")
        kommandoer += [f"ip address {ip_adresse} {nettmaske}", "no shutdown", "exit"]
        if ruting:
            kommandoer.append("ip routing")
        if gateway:
            kommandoer.append(
                f"ip route 0.0.0.0 0.0.0.0 {gateway}" if ruting
                else f"ip default-gateway {gateway}"
            )
        for kommando in kommandoer:
            konfigurer(konsoll, kommando)

        lag_ssh_nokler(konsoll)
        konfigurer(konsoll, "ip ssh version 2")
        sett_opp_vty(konsoll)
        svar = send(konsoll, "write memory", 5)
        if "[OK]" not in svar:
            raise RuntimeError("Lagring ble ikke bekreftet. Kontroller enheten manuelt.")
        print("\nIP-adresser og portstatus etter konfigurasjon:")
        send(konsoll, "show ip interface brief", 3)
        send(konsoll, "show ip ssh", 3)

    if vlan:
        print("\nVLAN-grensesnittet trenger en aktiv access-/trunkport i VLAN-et for å bli up.")
    print(f"\nOppsett lagret. Test tilkoblingen: ssh {brukernavn}@{ip_adresse}")


if __name__ == "__main__":
    try:
        hovedprogram()
    except (serial.SerialException, RuntimeError, ValueError) as feil:
        print(f"\nStoppet: {feil}\nEventuelle endringer før feilen kan fortsatt være aktive.")
        raise SystemExit(1)
