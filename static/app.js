async function checkStatus() {
    const areaSelect = document.getElementById("area");
    const result = document.getElementById("result");
    if (!areaSelect || !result) return;

    const area = areaSelect.value;
    if (!area) {
        result.className = "status-result error-text";
        result.textContent = "Please select your area first.";
        return;
    }

    result.className = "status-result muted-text";
    result.textContent = "Fetching community report summary...";
    try {
        const response = await fetch("/api/status/" + encodeURIComponent(area), {
            headers: { "Accept": "application/json" }
        });
        const data = await response.json();
        if (!response.ok) throw new Error("Status request failed");

        result.replaceChildren();
        const heading = document.createElement("strong");
        heading.textContent = "Community report summary for " + area;
        result.appendChild(heading);
        result.appendChild(document.createElement("br"));

        if (data.total === 0) {
            result.appendChild(document.createTextNode("No community reports have been submitted for this area."));
        } else {
            [
                ["Pending", "🟡"],
                ["In Progress", "🔵"],
                ["Resolved", "🟢"]
            ].forEach(([status, icon]) => {
                const line = document.createElement("p");
                line.textContent = icon + " " + status + ": " + (data.summary[status] || 0) + " report(s)";
                result.appendChild(line);
            });
            const total = document.createElement("p");
            total.className = "field-note";
            total.textContent = "Total community reports: " + data.total;
            result.appendChild(total);
        }
        const note = document.createElement("p");
        note.className = "field-note";
        note.textContent = "Electricity availability is unverified. Please confirm with your electricity provider.";
        result.appendChild(note);
        result.className = "status-result";
    } catch (error) {
        result.className = "status-result error-text";
        result.textContent = "Could not fetch the report summary. Please try again.";
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("check-status-button");
    if (button) button.addEventListener("click", checkStatus);
    const description = document.getElementById("problem");
    const counter = document.getElementById("character-count");
    if (description && counter) {
        const updateCount = () => { counter.textContent = description.value.length + " / 1000 characters"; };
        description.addEventListener("input", updateCount);
        updateCount();
    }
});
