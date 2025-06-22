ECHO OFF

set CMD=python scripts\run_strategy.py
set argCount=0
set M=
for %%x in (%*) do (
   set /A argCount+=1
)

cd \Investment\alpaca\options-wheel

CLS

call %CMD% --strat-log --log-level DEBUG --log-to-file

if %argCount% == 1 GOTO :END
GOTO :EXIT

:EXIT
exit
	
:END
ECHO ON

