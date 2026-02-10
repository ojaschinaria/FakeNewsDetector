document.getElementById('analyzeBtn').addEventListener('click', async () => {
    const btn = document.getElementById('analyzeBtn');
    const resultDiv = document.getElementById('result');
    const loader = document.getElementById('loader');
    const statusText = document.getElementById('status-text');
    const progressBar = document.getElementById('progress-bar');
    const explDiv = document.getElementById('explanation');
    
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    const stages = [
        { text: "Fetching title...", width: "20%" },
        { text: "Fetching sources...", width: "40%" },
        { text: "Fetching body...", width: "60%" },
        { text: "Verifying claims...", width: "80%" },
        { text: "Almost done...", width: "95%" }
    ];

    btn.disabled = true;
    loader.style.display = "block";
    resultDiv.innerText = "";
    explDiv.innerText = "";
    progressBar.style.width = "0%";

    let stageIdx = 0;
    const interval = setInterval(() => {
        if (stageIdx < stages.length) {
            statusText.innerText = stages[stageIdx].text;
            progressBar.style.width = stages[stageIdx].width;
            stageIdx++;
        }
    }, 1000);

    chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
            return {
                header: document.title || document.querySelector('h1')?.innerText || "",
                body: document.body.innerText.substring(0, 1500)
            };
        }
    }, (results) => {
        if (!results || !results[0].result) {
            clearInterval(interval);
            resetUI("Error: Script failed.", "orange");
            return;
        }

        const { header, body } = results[0].result;
        
        fetch('http://localhost:5000/predict', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ header, body })
        })
        .then(response => response.json())
        .then(data => {
            clearInterval(interval);
            loader.style.display = "none";
            btn.disabled = false;
            
            resultDiv.innerText = `${data.label} (${data.percentage}%)`;
            resultDiv.style.color = data.label === "Fake" ? "#ff4d4d" : "#2ecc71";
            explDiv.innerText = data.explanation;
        })
        .catch(error => {
            clearInterval(interval);
            resetUI("Error: Backend offline.", "orange");
        });
    });

    function resetUI(msg, color) {
        loader.style.display = "none";
        btn.disabled = false;
        resultDiv.innerText = msg;
        resultDiv.style.color = color;
    }
});