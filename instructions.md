
Step 1:
 
- This python automation downloads data from the website https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml while setting the following filters


        Y-Axis: Maker 
        X-Axis: Fuel
        Year Type: Calendar Year
        Year: Extract year from current_date - 1 day

        Click Refresh

        Maker Wise Fuel Data For All State (2026)
        Month: Extract Month from current_date - 1 day

        Click on the csv/excel icon to download the file


- Add Download the data to the folder vahan_data and add today's timestamp to the data.

Step2:  
- Clean the file by deleting the first three rows and renaming the first column as `S No` , second column as `Maker` and last column as `Total`
- Create a new column called `EV_Total` as sum of `PURE EV` and `ELECTRIC(BOV)`
- Sort the file by `EV_Total` and save to disk with same name.




Task 2: This instructions is only for `Market Share` tab. 

 Currently the Market share data uses all the `Vehicle Class` to compute market share. The market share should likely be computed using filters for example `Fuel`='Pure EV' and `Vehilce_Class` = 'M-Cycle/Scooter'. Since we do not have data at the level of `Maker` x `Fuel` x  `Vehicle Class`, we will have to do some approximation. Whenever `Fuel` = "Pure EV' and `Vehicle_Class`='M-Cycle/Scooter'. The ratio of registration for the maker when `Fuel`='Pure EV' to the total registrations in the month across all fuel types should be calculated and then multiplied by the registration numbers in the `Vehicle_Class`, then rounded to the nearest integer. This number should then be used to calcualte the markert share.


Task 3 - In the current flow to download data from the vahan portal script @vahan_download.py opens a browser, sets the correct filter and download
s the data. I am planning to move this script to a UI less server. Plan , get permission  and implement a different approach wherein the browser is not opened in the UI to download the data. Make a seperate script @vahan_daily_download_v2.py
