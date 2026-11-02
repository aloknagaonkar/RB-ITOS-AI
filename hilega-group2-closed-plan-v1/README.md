# Combined Group 2 closed recovery planning

One command verifies the installed closed recovery status before and after, checks the combined candidate files and context hashes, runs native pause recovery against two newly created disposable databases (paused and armed), and writes a closed deployment proposal with old/new release and wrapper hashes, proposed recovery config, maintenance steps and rollback steps. The rehearsal uses candidate bytes and a staged matching wrapper; it does not execute the wrapper or certify actual managed startup.

The proposal is not an executable deployment plan. Exact systemd upgrade payloads, transactional apply/rollback implementation, managed candidate validation and quiescent backups remain to be completed. No apply action exists. No broker reads, production authority creation, enrollment, live controller resume or application service changes occur. The installed status helper reads live state; the rehearsal only writes disposable state and the new review folder. No existing broker timestamp rule is weakened.

All behavioral validation runs on the user VM. Local checks are Python syntax and ZIP integrity only. Existing 74-case receipt is reused, not rerun. Failed checks stop and preserve private diagnostic logs in the new review folder.
