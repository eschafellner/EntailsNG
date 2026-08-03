import json
import logging
import urllib.request

logger = logging.getLogger(__name__)


def query_dns_json(domain, record_type='TXT'):
    """Fragt DNS-Records über die Google DNS REST API ab (zuverlässig & ohne externe Pip-Pakete)."""
    url = f"https://dns.google/resolve?name={domain}&type={record_type}"
    req = urllib.request.Request(
        url,
        headers={'Accept': 'application/json', 'User-Agent': 'EntailsNG-DNS-Checker/1.0'},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                answers = data.get('Answer', [])
                results = []
                for ans in answers:
                    val = ans.get('data', '').strip('"')
                    results.append(val)
                return results
    except Exception as e:
        logger.warning(f"DNS query error for {domain} ({record_type}): {e}")
    return []


def check_domain_dns_health(domain_name):
    """Führt eine umfassende DNS-Gesundheitsprüfung für die angegebene Domain durch."""
    if not domain_name:
        return {
            'status': 'error',
            'message': 'Keine Domain angegeben.',
            'spf': {'valid': False, 'details': 'Keine Domain hinterlegt'},
            'dmarc': {'valid': False, 'details': 'Keine Domain hinterlegt'},
            'mx': {'valid': False, 'details': 'Keine Domain hinterlegt'},
            'dkim': {'valid': False, 'details': 'Keine Domain hinterlegt'},
        }

    domain_clean = domain_name.strip().lower().replace('http://', '').replace('https://', '').split('/')[0]

    # 1. TXT Records für SPF & DKIM abfragen
    txt_records = query_dns_json(domain_clean, 'TXT')

    spf_record = None
    for r in txt_records:
        if 'v=spf1' in r:
            spf_record = r
            break

    # 2. DMARC Abfragen (_dmarc.domain)
    dmarc_records = query_dns_json(f"_dmarc.{domain_clean}", 'TXT')
    dmarc_record = None
    for r in dmarc_records:
        if 'v=dmarc1' in r.lower():
            dmarc_record = r
            break

    # 3. MX Records Abfragen
    mx_records = query_dns_json(domain_clean, 'MX')

    # 4. Häufige DKIM-Selektoren prüfen
    dkim_found = False
    dkim_selector = None
    common_selectors = ['default', 'mail', 'google', 'k1', 'smtp', 'mandrill']
    for sel in common_selectors:
        res = query_dns_json(f"{sel}._domainkey.{domain_clean}", 'TXT')
        for r in res:
            if 'v=dkim1' in r.lower() or 'p=' in r.lower():
                dkim_found = True
                dkim_selector = f"{sel}._domainkey.{domain_clean}"
                break
        if dkim_found:
            break

    # Empfehlungen generieren
    recommended_spf = "v=spf1 mx ~all"
    recommended_dmarc = f"v=DMARC1; p=none; rua=mailto:postmaster@{domain_clean}"

    return {
        'status': 'ok',
        'domain': domain_clean,
        'spf': {
            'valid': spf_record is not None,
            'record': spf_record or 'Fehlt im DNS',
            'details': 'SPF erlaubt dem Webserver/SMTP E-Mails für eure Domain zu versenden.' if spf_record else 'WARNUNG: Ohne SPF landen E-Mails oft im Spam-Ordner.',
            'recommended': recommended_spf,
        },
        'dmarc': {
            'valid': dmarc_record is not None,
            'record': dmarc_record or 'Fehlt im DNS',
            'details': 'DMARC schützt eure Domain vor E-Mail-Identitätsdiebstahl (Phishing).' if dmarc_record else 'Empfohlen: Ein grundlegender DMARC TXT-Eintrag schützt vor Spam-Klassifizierung.',
            'recommended': recommended_dmarc,
        },
        'mx': {
            'valid': len(mx_records) > 0,
            'records': mx_records or ['Keine MX-Einträge gefunden'],
            'details': 'MX-Einträge ermöglichen das Empfangen von E-Mails (z.B. Antworten von Gästen).' if mx_records else 'Kein Mailserver für den Empfang im DNS hinterlegt.',
        },
        'dkim': {
            'valid': dkim_found,
            'details': f'DKIM-Signatur gefunden unter: {dkim_selector}' if dkim_found else 'DKIM wird vom Mailserver/Hoster bereitgestellt (z. B. cPanel/Plesk/Postmaster).',
        },
    }
