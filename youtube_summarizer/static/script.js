document.addEventListener('DOMContentLoaded', function() {
    const searchButton = document.querySelector('.search-button');
    const videoQueryInput = document.getElementById('video-query');
    const languageLinks = document.querySelectorAll('.language-selector a');
    const logo = document.getElementById('theme-toggle');
    const chatQueryInput = document.getElementById('chat-query');
    const chatSubmitButton = document.getElementById('chat-submit');
    let isRequestPending = false;
    let latestRequestId = 0;
    let currentLanguage = 'en';
    let currentVideoId = null;

    // Theme toggle on logo click
    const currentTheme = localStorage.getItem('theme') || 'dark';
    document.body.className = currentTheme;

    logo.addEventListener('click', () => {
        const newTheme = document.body.className === 'light' ? 'dark' : 'light';
        document.body.className = newTheme;
        localStorage.setItem('theme', newTheme);
    });

    // Debounce function
    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // Language toggle
    function toggleLanguage(lang) {
        currentLanguage = lang;
        videoQueryInput.placeholder = lang === 'en' ? 'Search' : 'Rechercher';
        document.querySelector('.language-selector .active').classList.remove('active');
        document.querySelector(`[data-lang="${lang}"]`).classList.add('active');
    }

    // Animate loading dots
    function animateLoading(loadingDiv) {
        let dots = 0;
        return setInterval(() => {
            dots = (dots + 1) % 7;
            loadingDiv.innerHTML = '.'.repeat(dots);
        }, 300);
    }

    // Restore summary state if available
    const savedSummary = sessionStorage.getItem('summaryState');
    if (savedSummary) {
        const data = JSON.parse(savedSummary);
        currentVideoId = data.video_id;
        const resultDiv = document.getElementById('result');
        const chatContainer = document.getElementById('chat-container');
        resultDiv.style.display = 'block';
        chatContainer.style.display = 'block';
        resultDiv.innerHTML = `
            <h3>Summary</h3>
            <p class="summary-text">${data.summary}</p>
            <p><strong>Sentiment:</strong> ${data.sentiment || 'N/A'}</p>
            ${data.thumbnail ? `<img src="${data.thumbnail}" alt="Video Thumbnail" class="thumbnail">` : ''}
            <div class="action-buttons">
                ${data.url ? `<a href="${data.url}" target="_blank" class="action-button">Watch Video</a>` : ''}
                <a href="/audio-overview/${data.video_id}" class="action-button">Audio Overview</a>
            </div>
        `;
    }

    // Summarize video
    const summarize = debounce((query, requestId) => {
        if (isRequestPending || !query.trim()) {
            const resultDiv = document.getElementById('result');
            const loadingDiv = document.getElementById('loading');
            loadingDiv.style.display = 'none';
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = '<p>Please enter a valid YouTube URL or search query.</p>';
            return;
        }

        isRequestPending = true;
        const resultDiv = document.getElementById('result');
        const loadingDiv = document.getElementById('loading');
        const chatContainer = document.getElementById('chat-container');
        loadingDiv.style.display = 'block';
        const loadingAnimation = animateLoading(loadingDiv);
        resultDiv.style.display = 'none';
        chatContainer.style.display = 'none';
        resultDiv.innerHTML = '';
        videoQueryInput.value = '';
        currentVideoId = null; // Reset video ID to ensure new summary
        sessionStorage.removeItem('summaryState'); // Clear previous summary state

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 240000);
        const uniqueParam = `t=${Date.now()}`; // Add unique parameter to force fresh request

        fetch(`/summarize?${uniqueParam}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query }),
            signal: controller.signal
        })
        .then(response => {
            clearTimeout(timeoutId);
            clearInterval(loadingAnimation);
            if (!response.ok) throw new Error(`Error ${response.status}: ${response.statusText}`);
            return response.json();
        })
        .then(data => {
            if (requestId !== latestRequestId) return;
            loadingDiv.style.display = 'none';
            resultDiv.style.display = 'block';
            chatContainer.style.display = 'block';

            currentVideoId = data.video_id;
            resultDiv.innerHTML = `
                <h3>Summary</h3>
                <p class="summary-text">${data.summary}</p>
                <p><strong>Sentiment:</strong> ${data.sentiment || 'N/A'}</p>
                ${data.thumbnail ? `<img src="${data.thumbnail}" alt="Video Thumbnail" class="thumbnail">` : ''}
                <div class="action-buttons">
                    ${data.url ? `<a href="${data.url}" target="_blank" class="action-button">Watch Video</a>` : ''}
                    <a href="/audio-overview/${data.video_id}" class="action-button">Audio Overview</a>
                </div>
            `;
            // Save summary state
            sessionStorage.setItem('summaryState', JSON.stringify(data));
        })
        .catch(error => {
            clearTimeout(timeoutId);
            clearInterval(loadingAnimation);
            if (requestId !== latestRequestId) return;
            loadingDiv.style.display = 'none';
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = `<p>${error.message.includes('Error') ? error.message : 'An error occurred. Please try again later.'}</p>`;
        })
        .finally(() => {
            isRequestPending = false;
            searchButton.disabled = false;
        });
    }, 300);

    // Chat function
    const sendChatMessage = debounce((question) => {
        if (!question.trim() || !currentVideoId) {
            if (!currentVideoId) alert("Please summarize a video first.");
            return;
        }

        const chatMessages = document.getElementById('chat-messages');
        const chatLoading = document.getElementById('chat-loading');
        // Display user message in a bubble without "You:"
        chatMessages.innerHTML += `<div class="chat-message user"><div class="message-content">${question}</div></div>`;
        chatMessages.scrollTop = chatMessages.scrollHeight;
        chatLoading.style.display = 'block';
        const loadingAnimation = animateLoading(chatLoading);

        fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ video_id: currentVideoId, question: question })
        })
        .then(response => {
            clearInterval(loadingAnimation);
            chatLoading.style.display = 'none';
            if (!response.ok) throw new Error(`Error ${response.status}: ${response.statusText}`);
            return response.json();
        })
        .then(data => {
            // Display AI response without "YouNote:" and without a bubble
            chatMessages.innerHTML += `<div class="chat-message bot"><div class="message-content">${data.answer}</div></div>`;
            chatMessages.scrollTop = chatMessages.scrollHeight;
        })
        .catch(error => {
            chatMessages.innerHTML += `<div class="chat-message bot"><div class="message-content">Error: ${error.message}</div></div>`;
            chatMessages.scrollTop = chatMessages.scrollHeight;
        })
        .finally(() => {
            chatLoading.style.display = 'none';
        });

        chatQueryInput.value = '';
    }, 300);

    // Event listeners
    languageLinks.forEach(link => {
        link.addEventListener('click', (event) => {
            event.preventDefault();
            toggleLanguage(link.getAttribute('data-lang'));
        });
    });

    searchButton.addEventListener('click', (event) => {
        event.preventDefault();
        const query = videoQueryInput.value.trim();
        if (!query) return;
        searchButton.disabled = true;
        latestRequestId++;
        summarize(query, latestRequestId);
    });

    videoQueryInput.addEventListener('keypress', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            const query = videoQueryInput.value.trim();
            if (!query) return;
            searchButton.disabled = true;
            latestRequestId++;
            summarize(query, latestRequestId);
        }
    });

    chatSubmitButton.addEventListener('click', () => {
        sendChatMessage(chatQueryInput.value.trim());
    });

    chatQueryInput.addEventListener('keypress', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            sendChatMessage(chatQueryInput.value.trim());
        }
    });

    toggleLanguage('en');
});