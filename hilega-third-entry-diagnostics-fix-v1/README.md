# Third-entry diagnostics fixture correction

The first 80-case VM run reported 73 passed, seven failed. The seven failures
were blocked by DIAGNOSTICS_REQUIRED: the new fixture copied account diagnostics
over an already-valid cash diagnostic envelope. This correction copies only
orders, trades and positions, preserves existing cash diagnostics, and signs the
resulting synthetic fixture as before. Cash validation is unchanged.

Extract this ZIP into the checkout and run:

```bash
.venv/bin/python hilega-third-entry-diagnostics-fix-v1/fix_and_test.py --repo "$PWD"
```

The script accepts only the exact originally delivered test file or the exact
corrected file. It updates the isolated home test and the original package's
test/checksum when present, then reruns the full regression on the VM. It does
not change trading candidate implementations, installed services, production
databases or execution permission. Behavioral outcome remains pending the VM run.
