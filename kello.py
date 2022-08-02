# Kello

time_now_str = input("What is time now?")
how_long_wait =  input("How long do you want to wait?")

time_now_int = int(time_now_str)
how_long_wait_int = int(how_long_wait)

alarm_goes_off = time_now_int + how_long_wait_int
alarm = alarm_goes_off % 24
print(alarm)

laske = time_now_str * how_long_wait
print(laske)
