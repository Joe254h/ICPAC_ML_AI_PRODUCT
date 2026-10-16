set pagination off
set print thread-events off
run
if $_isvoid($_exitcode)
    thread apply all bt 40
    quit 1
end
quit $_exitcode
