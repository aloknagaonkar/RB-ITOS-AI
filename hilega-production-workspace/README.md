# Upstox Production workspace — integration milestone2

Prepared against the uploaded source ZIP. Archive comment:6c93afbb6531a7d3a4e1026141ff362aa6e736df. Reported VM HEAD:8c156daa0cf233cae449b5eafd8264bb8b915a23. These differ. The installer compares the exact active App.tsx/api.py hashes and refuses to overwrite differing files. Do not bypass a mismatch; provide those current files for rebasing.

## What changes

- New Upstox Production sidebar page in both normal and PCR-loading layouts.
- Compact link on Hilega to the new workspace. Existingstrategy/observation/Sandbox rules remain unchanged.
- Six sections:Overview,Activepositions,Orders&fills,Closedtrades,Executionsettings,Readiness&audit. Blockedhypotheticaloutcomes is explicitlypending.
- AuthenticatedGETstatus andPOSTcommands; sharedbackendService is used by UI and newHTTPCLI.
- Automatic2second displaypolling,timeout,focusrecovery,staledisplayindicator,backendacknowledgementsandversionedcommands.
- SIMULATION_ONLY mode:durablepause/resume/exit/flatten/reconciliation with5secondservermonitor independentofbrowser. APIstartupblocksentriesuntilreconciliationandexplicitresume.
- DefaultDISABLED: no control of currentstrategyworker, SandboxworkerorUpstox.

IMPORTANT: Buttons are explicitly marked SIM. They control only the simulator. The current live/Sandbox workers do NOT use this gate yet. Do not rely on this page's pause to stop those workers. Productionordertransport, realpositions, livecash/P&L, quoteupdates, automaticexternalexitattribution,configediting, shadowoutcomesandreadinessprobes are NOT implemented. They are displayed as unavailable/notvalidated, never fabricated.

##1. Check and stage on VM

Extract this directory into ~/RB-ITOS-AI.

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
set +e

.venv/bin/python hilega-production-workspace/install.py

.venv/bin/python hilega-production-workspace/install.py \
  --stage data/research/hilega-production-workspace-stage
```

If TARGET_DIFFERS_FROM_UPLOADED_SOURCE appears, stop. Installerhasnotmodifiedapplicationfiles. Sendtheerrorandcurrentfrontend/src/App.tsxandbackend/market_lab/api.py. Stagingrequiresanewnonexistentpath. No servicesstart.

##2. Run validation on your VM

```bash
.venv/bin/python hilega-production-workspace/validate.py \
  --stage data/research/hilega-production-workspace-stage \
  --output data/research/hilega-production-workspace-validation.json
```

Runs 47 new tests (34 foundation + 13 API), existing strategy/dispatch regression tests, and the staged frontend build. Usesproject.venv/npm;frontend/node_modules is linked read-only forbuildinputfromexistingproject;buildoutputgoestostagefrontend/dist. Existingapplicationservicesarenotrestarted. No realbrokerorders. Tests/buildswereNOTexecutedlocally;Pythonwas syntax-parsedonly. PASSdoesnotmeanproductionready.

##3. Apply only after PASS

```bash
.venv/bin/python hilega-production-workspace/install.py --apply \
  --validation data/research/hilega-production-workspace-validation.json

npm --prefix frontend run build
bash scripts/restart_hilega_ui_api_safe.sh
```

Appliesonlylistedfiles,createsbackupandrollbackmanifest,doesnotstartservicesororders. TherestartcommandistheseparateexistingAPI-onlysafescript;verifyitsstrategyworkerPIDbefore/aftermessage. Do not use a full worker restart for this UI milestone. DefaultmodeisDISABLED.

##4. Configure workspace authentication and simulator (optional)

No Upstoxaccess/sandboxtokensareneeded. CreateaSEPARATEworkspacecontrolkey,outsideGit:

```bash
mkdir -p ~/hilega-private
chmod 700 ~/hilega-private
.venv/bin/python - <<'PYCODE'
from pathlib import Path
import secrets,os
p=Path.home()/'hilega-private/production-workspace.token'
fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(48)+'\n')
print('Workspace key created; value not printed.')
PYCODE
```

If thekeyfilealreadyexists,keepit;donotoverwriteitwhileanotherclientisusingit. Add/update these settings in the API's existing local environment configuration, using your absolute home path:

```text
HILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY
HILEGA_PRODUCTION_CONTROL_TOKEN_FILE=/home/aloknagaonkar46/hilega-private/production-workspace.token
```

For disabledpreviewuseMODE=DISABLED instead. Do not setLIVE;unsupportedmodesfailclosedforthisworkspace. These settings do not arm realexecution. ReloadAPIusingtheexistingAPI-onlysafe restartscript aftersettingschanges.

UseHTTPSorSSHforwardingtoaccessUI. OpenUpstoxProduction,entertheseparateworkspacekeyandConnect. Key only in page memory;notlocalStorage/URL. Readthekeylocallyforpasting,neversenditinchat/logs. Authenticationcurrentlyidentifiesasharedcontrolcredential,notindividualusers;per-userroles/identityarefuturework. Existingappauthenticationisnotreplaced. NewroutesrequiresameOriginforbrowserrequests. RunUI/APIonasameorigin.

##5. CLI uses the SAME API and simulator state as UI

```bash
.venv/bin/python scripts/hilega_production_control.py \
  --token-file ~/hilega-private/production-workspace.token status

.venv/bin/python scripts/hilega_production_control.py \
  --token-file ~/hilega-private/production-workspace.token pause-today

.venv/bin/python scripts/hilega_production_control.py \
  --token-file ~/hilega-private/production-workspace.token reconcile
```

Getcurrentcontrolversion/sessiondatefromstatusbeforeexplicitresume:

```bash
.venv/bin/python scripts/hilega_production_control.py \
  --token-file ~/hilega-private/production-workspace.token resume \
  --next-signal --expected-version REPLACE_WITH_CURRENT_VERSION \
  --session-date YYYY-MM-DD
```

Othercommands:exit --position-idID --expected-versionN --session-dateYYYY-MM-DD;flatten-and-pause. UsesGET/POSTonlytolocalworkspaceAPI,neverUpstox. Requesttimeoutsarenotautomaticallyretried. Same requestIDcanbeprovidedwith--request-idforidempotentretrievalbutpayloadmustmatch. Statusdoesnotchangepermissions. No entryCLI exists;testsprovidefakeorders. EmptytablemeansnoSIMpositions,notproofofanemptybrokeraccount.

## Browser-independent acceptance checks

1.PauseusingUI,readsameversion/modefromCLI.
2.Refreshbrowser/reopenpage:serverstatepersists;UIreauthenticationrequired.
3.Closebrowser:5secondserverreconciliationcontinues;verifylast_reconciled_atthroughCLI.
4.RestartAPIwhileSIMarmed:startupmustpauseagain;noautomaticresume.
5.Useoldcontrolversiontoresume:HTTP409;pausecannotbeundonebystaleclient.
6.Remove/wrongkey:401/503;nocontrolmutation.
7.StopAPI:UImarksdisplaystale;doesnotclaimpause/resumesucceeded.
8.ModeDISABLED:allSIMcontrolsdisabled;productionexecutionfalse.
9.Activepositionsandfillfaultsusethe34foundationtests;realUpstoxfillsareNOTvalidated.

## Remaining production work

Wireconfirmedstrategyintentsintothesafetygate;explicitbrokerownershipledger;liveUpstoxadapter;funds/IP/token/quotevalidation;actualpartialfill/externalexitreconciliation;realP&L;50%cashreservationandcontractconfiguration;daily-risklimits;fullmarketshadowandpilot. Independentbodyresearchisnotpromoted. Today controls shown here apply to SIMonly.

## Rollback

InstallerprintsbackupdirectorycontainingoriginalApp.tsx/api.pyandrollback.json. Stopusingtheworkspace,restorethoseoriginalfilesfrombackup,removeonlynewfileslistedundercreatedinrollback.json,rebuildfrontendandAPI-onlyrestart. Donotdeleterealexecutionjournals. Simulationstateisseparateunderdata/research/hilega-production-workspace. No currentstrategyfilesaremodifiedbythispackage.
