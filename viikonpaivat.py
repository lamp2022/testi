
when_leave_str = input("When do you leave?")
what_length_str = input("What lenght?")

when_leave = int(when_leave_str)
what_length = int(what_length_str)

paluu = (when_leave + what_length) % 7
print(paluu)

######
#####
