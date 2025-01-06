function startCountdown() {
    var timeLeft = 900;
    var isReloading = false;
    
    function updateTimer() {
        var min = Math.floor(timeLeft / 60);
        var sec = timeLeft % 60;
        
        if (min < 10) min = "0" + min;
        if (sec < 10) sec = "0" + sec;
        
        document.getElementById("countdown").textContent = min + ":" + sec;
        
        if (timeLeft <= 0 && !isReloading) {
            isReloading = true;
            setTimeout(function() {
                location.reload();
            }, 1000);
        } else {
            timeLeft--;
        }
    }
    
    updateTimer();
    setInterval(updateTimer, 1000);
} 