# Nettverksoppsett med Ansible

Oppsettet konfigurerer to rutere og tre svitsjer. Python-skriptet setter opp SSH via konsoll. Deretter bruker Ansible SSH til å sette opp VLAN, ruting og DHCP.

## 1. Filer

Legg alle filene i samme mappe, for eksempel `nettverk`.

| Filer | Bruk |
| --- | --- |
| `ssh_setup.py` | Klargjør SSH via konsoll |
| `ansible.cfg` | Innstillinger for Ansible |
| `hosts.ini` | IP-adresser og innlogging |
| `msw1.yml` | Hovedsvitsj og OSPF |
| `r1.yml` | Ruter for VLAN 10 |
| `r2.yml` | Ruter for VLAN 20 |
| `sw2.yml` | VLAN og forbindelser mellom enhetene |
| `sw3.yml` | Klientporter og VLAN |
| `verify.yml` | Viser status for oppsettet |


## 2. IP-plan

Alle nettene bruker nettmasken `255.255.255.0` (/24).

| Enhet | IP-adresse | Grensesnitt |
| --- | --- | --- |
| Ekstern gateway | 10.1.0.1 | Tilkoblet VLAN 99 |
| R1 | 10.1.0.2 | Gi0/0/1 |
| R2 | 10.1.0.3 | Gi0/0/1 |
| MSW1 | 10.1.0.100 | Vlan99 |
| SW2 | 10.1.0.101 | Vlan99 |
| SW3 | 10.1.0.102 | Vlan99 |
| Ansible-PC (forslag) | 10.1.0.10 | Nettverkskort |

| VLAN | Bruk | Nettverk | Klientgateway | DHCP-område |
| --- | --- | --- | --- | --- |
| 99 | Administrasjon | 10.1.0.0/24 | – | Ingen |
| 10 | Klienter via R1 | 10.1.10.0/24 | 10.1.10.1 | 10.1.10.11–10.1.10.127 |
| 20 | Klienter via R2 | 10.1.20.0/24 | 10.1.20.1 | 10.1.20.11–10.1.20.127 |

R1 har adressen `10.1.10.2` i VLAN 10. R2 har `10.1.20.3` i VLAN 20. Klientgatewayene er virtuelle HSRP-adresser.

## 3. Koble utstyret

Kontroller at portnavnene stemmer med det fysiske utstyret.

| Fra | Til | Portmodus på svitsjen |
| --- | --- | --- |
| MSW1 Gi1/0/1 | R1 Gi0/0/1 | Access VLAN 99 |
| MSW1 Gi1/0/2 | R2 Gi0/0/1 | Access VLAN 99 |
| MSW1 Gi1/0/3 | Ansible-PC | Access VLAN 99 |
| SW2 Fa0/2 | SW3 Gi1/0/3 | Trunk VLAN 10,20,99 |
| SW2 Fa0/3 | R1 Gi0/0/0 | Trunk VLAN 10 |
| SW2 Fa0/4 | R2 Gi0/0/0 | Trunk VLAN 20 |
| SW2 Fa0/5 | Ekstern gateway | Access VLAN 99 |
| SW3 Gi1/0/1 | Klient i VLAN 10 | Access VLAN 10 |
| SW3 Gi1/0/2 | Klient i VLAN 20 | Access VLAN 20 |

**Administrasjon må tilpasses:** Veien fra MSW1 til de nedre svitsjene går via R1/R2. Med dagens filer ligger SW2 og SW3 i samme IP-subnett som MSW1, men på et adskilt lag 2-nett. Ansible-PC-en kan derfor ikke nå SW2 og SW3 med dette oppsettet. Et eget administrasjonssubnett med ruting via en av ruterne må konfigureres før disse playbookene kan kjøres fra PC-en.

## 4. Installer verktøyene

Kjør dette på Ansible-PC-en med Ubuntu/Linux, fra mappen med filene:

```bash
sudo apt update
sudo apt install python3-pip python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install ansible paramiko pyserial
ansible-galaxy collection install cisco.ios ansible.netcommon
```

Åpner du en ny terminal, gå til samme mappe og kjør `source .venv/bin/activate` igjen.

## 5. Klargjør SSH først

Koble konsollkabelen til én enhet om gangen og kjør:

```bash
python ssh_setup.py
```

Velg riktig enhetstype, IP-adresse og grensesnitt fra IP-planen. Bruk for eksempel domenet `lab.local`. Konsollporten er vanligvis `/dev/ttyUSB0`, men må passe maskinen din.

På svitsjene bruker du `Vlan99` som IP-grensesnitt. Klargjør administrasjonsforbindelsene slik:

| Enhet | Accessporter i VLAN 99 | Trunkporter som må føre VLAN 99 |
| --- | --- | --- |
| MSW1 | Gi1/0/1,Gi1/0/2,Gi1/0/3 | Ingen |
| SW2 | Fa0/5 | Fa0/2 |
| SW3 | Ingen nødvendige for administrasjon | Gi1/0/3 |

Bruk `Gi0/0/1` som IP-grensesnitt på begge ruterne. Gateway er `10.1.0.1`. Sett Ansible-PC-en til en ledig adresse, for eksempel `10.1.0.10/24`.

`hosts.ini` bruker brukernavnet og passordet `cisco`. Endre disse til det du faktisk satte i skriptet. Brukeren må ha privilege 15, som skriptet setter opp.

Test fra Ansible-PC-en, og gjenta for de andre IP-adressene:

```bash
ping 10.1.0.100
ssh cisco@10.1.0.100
```

**SSH må fungere før du kjører Ansible.** Det holder med én tilgjengelig administrasjonsadresse per enhet. Hver svitsjport trenger ikke egen IP-adresse.

## 6. Kjør Ansible

Når administrasjonsrutingen er tilpasset og SSH er testet mot alle enhetene, kjør fra mappen med `ansible.cfg` og `hosts.ini`:

```bash
ansible-inventory --graph
ansible-playbook msw1.yml
ansible-playbook sw2.yml
ansible-playbook sw3.yml
ansible-playbook r1.yml
ansible-playbook r2.yml
```

Kjør én fil om gangen. Rett eventuelle feil før du fortsetter. Hver konfigurasjonsfil lagrer endringene på enheten.

## 7. Kontroller resultatet

```bash
ansible-playbook verify.yml
```

Filen viser IP-adresser, OSPF, HSRP, DHCP, VLAN og trunker. Resultatene må leses manuelt; den avgjør ikke automatisk om hele nettverket fungerer.

- Kontroller at administrasjonsgrensesnittene er `up/up`.
- Kontroller at MSW1, R1 og R2 får OSPF-naboer.
- Sett klientene til DHCP og kontroller adresse og gateway mot tabellen.
- Ping egen gateway og deretter en klient i det andre VLAN-et.

## Vanlige problemer

| Problem | Kontroller |
| --- | --- |
| Kan ikke koble til port 22 | IP-adresse, kabler, VLAN 99 og at SSH er aktivert |
| `Permission denied` | Brukernavn og passord i `hosts.ini` |
| VLAN-grensesnittet er nede | Minst én aktiv port må føre VLAN-et |
| Klienten får 169.254.x.x | Klientportens VLAN, trunk mot ruteren og DHCP |
| Cisco avviser en kommando | At portnavn og kommando støttes av modellen |

## Begrensninger i disse filene

- HSRP er konfigurert, men ingen reserveruter er satt opp i samme klient-VLAN. Filene gir derfor ikke gateway-redundans alene.
- EtherChannel er deaktivert i `sw3.yml` (`enable_etherchannel: false`).
- Ekstern gateway `10.1.0.1` må settes opp separat. Internett krever også nødvendig returruting og eventuell NAT. DHCP-poolene deler ikke ut DNS-server.
- Innloggingsdata i klartekst og avslått kontroll av SSH-vertsnøkler er ment for en isolert skolelab.
