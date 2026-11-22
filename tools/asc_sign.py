"""App Store signing for the TestFlight workflow, done with the App Store Connect API (no Mac, no Xcode account).

  python3 tools/asc_sign.py setup    -> distribution certificate + App Store profile for this run
  python3 tools/asc_sign.py cleanup  -> revokes that certificate and deletes that profile

Why: Xcode's cloud signing re-signs an unsigned archive and drops its entitlements (the increased memory limit the
whole game needs). Signing the archive itself with a real distribution identity keeps them. The certificate only
lives for one run (revoking a distribution certificate does not affect builds already uploaded to Apple), so runs
never pile up against Apple's certificate limit.

Env: ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH, BUNDLE_ID, WANT_MEMORY (true/false), WORK (temp dir), P12_PASS,
GITHUB_ENV, GITHUB_RUN_NUMBER.
"""
import base64, json, os, subprocess, sys, time

import jwt
import requests

API = 'https://api.appstoreconnect.apple.com/v1/'
WORK = os.environ['WORK']
STATE = os.path.join(WORK, 'sign_state.json')


def token():
    now = int(time.time())
    return jwt.encode({'iss': os.environ['ASC_ISSUER_ID'], 'iat': now, 'exp': now + 1200, 'aud': 'appstoreconnect-v1'},
                      open(os.environ['ASC_KEY_PATH']).read(), algorithm='ES256',
                      headers={'kid': os.environ['ASC_KEY_ID'], 'typ': 'JWT'})


H = {'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json'}


def call(method, path, body=None, ok=(200, 201, 204), **params):
    r = requests.request(method, API + path, headers=H, params=params or None, data=json.dumps(body) if body else None)
    if r.status_code not in ok:
        print('::error::App Store Connect', method, path, '->', r.status_code, r.text[:800])
        raise SystemExit(1)
    return r.json() if r.text else {}


def env_out(**kv):
    with open(os.environ['GITHUB_ENV'], 'a') as f:
        for k, v in kv.items(): f.write('%s=%s\n' % (k, v))


def run(*cmd):
    subprocess.run(cmd, check=True)


def setup():
    bundle = os.environ['BUNDLE_ID']
    ids = call('GET', 'bundleIds', **{'filter[identifier]': bundle, 'limit': 20})
    bid = next((x['id'] for x in ids.get('data', []) if x['attributes']['identifier'] == bundle), None)
    if not bid:
        print('::error::Bundle ID', bundle, 'is not registered in the developer account'); raise SystemExit(1)

    memory_ok = False
    if os.environ.get('WANT_MEMORY', 'true') == 'true':
        caps = call('GET', 'bundleIds/%s/bundleIdCapabilities' % bid)
        have = {c['attributes'].get('capabilityType') for c in caps.get('data', [])}
        print('Bundle ID capabilities:', sorted(x for x in have if x))
        if 'INCREASED_MEMORY_LIMIT' in have:
            memory_ok = True
        else:
            r = requests.post(API + 'bundleIdCapabilities', headers=H, data=json.dumps({'data': {
                'type': 'bundleIdCapabilities', 'attributes': {'capabilityType': 'INCREASED_MEMORY_LIMIT'},
                'relationships': {'bundleId': {'data': {'type': 'bundleIds', 'id': bid}}}}}))
            memory_ok = r.status_code in (200, 201)
            print('Turned on Increased Memory Limit for', bundle, '->', r.status_code, '' if memory_ok else r.text[:400])
    env_out(MEMORY_OK='1' if memory_ok else '0')

    key = os.path.join(WORK, 'dist_key.pem'); csr = os.path.join(WORK, 'dist.csr')
    run('/usr/bin/openssl', 'genrsa', '-out', key, '2048')
    run('/usr/bin/openssl', 'req', '-new', '-key', key, '-subj', '/CN=RUNA CI', '-out', csr)
    r = requests.post(API + 'certificates', headers=H, data=json.dumps({'data': {'type': 'certificates', 'attributes': {
        'certificateType': 'DISTRIBUTION', 'csrContent': open(csr).read()}}}))
    if r.status_code not in (200, 201):
        print('::error::Could not create a distribution certificate:', r.status_code, r.text[:600])
        have = call('GET', 'certificates', **{'filter[certificateType]': 'DISTRIBUTION,IOS_DISTRIBUTION', 'limit': 20})
        for c in have.get('data', []):
            a = c['attributes']; print('  existing distribution certificate, expires', a.get('expirationDate'))
        print('If the limit is reached: developer.apple.com > Certificates, revoke an unused Distribution certificate.')
        raise SystemExit(1)
    cert = r.json()['data']
    state = {'cert_id': cert['id']}
    json.dump(state, open(STATE, 'w'))
    der = os.path.join(WORK, 'dist.cer'); pem = os.path.join(WORK, 'dist_cert.pem'); p12 = os.path.join(WORK, 'dist.p12')
    open(der, 'wb').write(base64.b64decode(cert['attributes']['certificateContent']))
    run('/usr/bin/openssl', 'x509', '-inform', 'der', '-in', der, '-out', pem)
    run('/usr/bin/openssl', 'pkcs12', '-export', '-inkey', key, '-in', pem, '-out', p12, '-passout', 'pass:' + os.environ['P12_PASS'])
    print('Distribution certificate for this run created')

    name = 'RUNA App Store CI %s' % os.environ.get('GITHUB_RUN_NUMBER', int(time.time()))
    prof = call('POST', 'profiles', {'data': {'type': 'profiles', 'attributes': {'name': name, 'profileType': 'IOS_APP_STORE'},
        'relationships': {'bundleId': {'data': {'type': 'bundleIds', 'id': bid}},
                          'certificates': {'data': [{'type': 'certificates', 'id': cert['id']}]}}}})['data']
    state['profile_id'] = prof['id']; json.dump(state, open(STATE, 'w'))
    uuid = prof['attributes']['uuid']; content = base64.b64decode(prof['attributes']['profileContent'])
    for d in ('~/Library/MobileDevice/Provisioning Profiles', '~/Library/Developer/Xcode/UserData/Provisioning Profiles'):
        d = os.path.expanduser(d); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, uuid + '.mobileprovision'), 'wb').write(content)
    print('App Store profile for this run:', name, uuid)
    env_out(SIGN_P12=p12, SIGN_PROFILE_NAME=name, SIGN_PROFILE_UUID=uuid)


def cleanup():
    if not os.path.isfile(STATE): print('nothing to clean up'); return
    state = json.load(open(STATE))
    if state.get('profile_id'):
        call('DELETE', 'profiles/%s' % state['profile_id'], ok=(200, 204, 404)); print('deleted the run\'s profile')
    if state.get('cert_id'):
        call('DELETE', 'certificates/%s' % state['cert_id'], ok=(200, 204, 404)); print('revoked the run\'s certificate')


{'setup': setup, 'cleanup': cleanup}[sys.argv[1]]()
