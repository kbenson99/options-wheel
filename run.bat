ECHO OFF

set CMD=python scripts\run_strategy.py
set argCount=0
set M=
for %%x in (%*) do (
   set /A argCount+=1
)

cd \Investment\alpaca\options-wheel

CLS

call %CMD% --strat-log --log-level DEBUG --log-to-file %*


IF /I "%~1" == "--test" (
    GOTO :END
) ELSE (
	GOTO :EXIT
)


:EXIT
exit
	
:END
ECHO ON

