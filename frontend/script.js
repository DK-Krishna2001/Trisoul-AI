const BACKEND_URL = "http://localhost:8000";
let USER_ID = null;

// Helper to convert backend naive UTC timestamps to local timezone dates
function getLocalDate(utcDateStr) {
    if (!utcDateStr) return new Date();
    // If it's a string missing the 'Z', append it so the browser parses it as UTC
    if (typeof utcDateStr === 'string' && !utcDateStr.endsWith('Z') && !utcDateStr.includes('+')) {
        return new Date(utcDateStr + 'Z');
    }
    return new Date(utcDateStr);
}

// DOM Elements
const moodSidebar = document.getElementById('moodSidebar');
const openSidebarBtn = document.getElementById('openSidebarBtn');
const closeSidebarBtn = document.getElementById('closeSidebarBtn');

// Landing Page Elements
const landingPage = document.getElementById('landingPage');
const mainAppContainer = document.getElementById('mainAppContainer');
const getStartedBtn = document.getElementById('getStartedBtn');
const authModal = document.getElementById('authModal');

// Set initial history state for the landing page
document.addEventListener('DOMContentLoaded', () => {
    history.replaceState({ page: 'landing' }, 'Trisoul Landing', window.location.pathname);

    if (getStartedBtn) {
        getStartedBtn.addEventListener('click', () => {
            // Push new state to history stack
            history.pushState({ page: 'app' }, 'Trisoul App', '#app');

            // Fade out landing page
            landingPage.style.opacity = '0';
            setTimeout(() => {
                landingPage.classList.remove('active');
                landingPage.style.display = 'none';

                // Show main app container initially, but...
                mainAppContainer.style.display = 'flex';

                // If user is not logged in (USER_ID is null), show auth modal manually
                if (!USER_ID) {
                    authModal.classList.add('active');
                    // Hide the app container behind the modal so it doesn't peek through the glassmorphism
                    mainAppContainer.style.display = 'none';
                }
            }, 500); // match CSS fade-out transition duration
        });

        // Listen for browser back/forward buttons & swipe gestures
        window.addEventListener('popstate', (event) => {
            if (!event.state || event.state.page !== 'app') {
                // We are back at the landing page
                authModal.classList.remove('active');
                mainAppContainer.style.display = 'none';
                landingPage.style.display = 'flex';
                setTimeout(() => {
                    landingPage.style.opacity = '1';
                    landingPage.classList.add('active');
                }, 50);
            } else {
                // User navigated forward to the app manually
                landingPage.style.opacity = '0';
                landingPage.classList.remove('active');
                landingPage.style.display = 'none';

                mainAppContainer.style.display = 'flex';

                if (!USER_ID) {
                    authModal.classList.add('active');
                    mainAppContainer.style.display = 'none'; // hide app while auth is active
                }
            }
        });

        // Back Button on Auth Modal
        const authBackBtn = document.getElementById('authBackBtn');
        if (authBackBtn) {
            authBackBtn.addEventListener('click', () => {
                // Triggers the popstate event naturally to go back to the landing page
                history.back();
            });
        }
        const chatWrapper = document.getElementById('chatWrapper');
        const messageInput = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');
        const recordBtn = document.getElementById('recordBtn');
        const recordingIndicator = document.getElementById('recordingIndicator');
        const recentInsights = document.getElementById('recentInsights');
        const chatHistoryList = document.getElementById('chatHistoryList');
        const newChatBtnPrimary = document.getElementById('newChatBtnPrimary');

        // Attachment UI Elements
        const attachBtn = document.getElementById('attachBtn');
        const fileInput = document.getElementById('fileInput');
        const attachmentPreviewBox = document.getElementById('attachmentPreviewBox');
        const attachmentName = document.getElementById('attachmentName');
        const attachmentIcon = document.getElementById('attachmentIcon');
        const removeAttachmentBtn = document.getElementById('removeAttachmentBtn');

        // Attachment Menu Elements
        const attachmentMenu = document.getElementById('attachmentMenu');
        const attachImageBtn = document.getElementById('attachImageBtn');
        const attachFileBtn = document.getElementById('attachFileBtn');
        let currentAttachment = null;

        const openGlobalDashboardBtn = document.getElementById('openGlobalDashboardBtn');
        const closeGlobalDashboardBtn = document.getElementById('closeGlobalDashboardBtn');
        const globalDashboardModal = document.getElementById('globalDashboardModal');

        // State
        let chartInstance = null;
        let speechRecognition = null;
        let isRecording = false;
        let liveTranscriptionId = null; // Track the ID of the live transcription bubble

        // Initialize SpeechRecognition if available
        if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            speechRecognition = new SpeechRecognition();
            speechRecognition.continuous = true;
            speechRecognition.interimResults = true;
            speechRecognition.lang = 'en-US';

            speechRecognition.onresult = (event) => {
                let interimTranscript = '';
                let finalTranscript = '';

                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }

                // Update input box with either final or interim text
                const currentText = messageInput.value;
                const totalText = finalTranscript + interimTranscript;

                // Keep input box updated
                messageInput.value = totalText;

                // Update the live chat bubble if it exists
                if (liveTranscriptionId) {
                    const liveBubble = document.getElementById(liveTranscriptionId);
                    if (liveBubble) {
                        const innerTextDiv = liveBubble.querySelector('.markdown-body');
                        if (innerTextDiv) {
                            innerTextDiv.innerHTML = totalText || "...listening...";
                        }
                    }
                    scrollToBottom();
                }
            };

            speechRecognition.onspeechend = () => {
                // Many browsers fire this when they think the user stopped speaking. 
                // We want to keep listening unconditionally until the user clicks 'stop'.
                if (isRecording) {
                    try { speechRecognition.stop(); } catch (e) { }
                }
            };

            speechRecognition.onerror = (event) => {
                console.error("Speech recognition error", event.error);
                stopRecording();
            };

            speechRecognition.onend = () => {
                // Only stop if we actually toggled it off, otherwise it might have just paused
                // Browsers often auto-stop after 10-15 seconds of silence or after a single sentence.
                if (isRecording) {
                    try {
                        speechRecognition.start(); // Keep listening!
                    } catch (e) {
                        console.error("Could not restart speech recognition", e);
                    }
                }
            };
        }


        function generateSessionId() {
            return 'session_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
        }
        let currentSessionId = generateSessionId();

        // Initialize when user logs in via Firebase (auth.js calls this)
        window.initializeAppWithUser = function (uid) {
            USER_ID = uid;

            // Auth was successful, so make sure to show the app container
            const appContainer = document.getElementById('mainAppContainer');
            if (appContainer) appContainer.style.display = 'flex';

            chatWrapper.innerHTML = `
        <div class="welcome-message">
            <div class="welcome-icon"><i class="fa-solid fa-leaf"></i></div>
            <h2>Welcome to Trisoul</h2>
            <p>I'm here to listen, support, and help you navigate your thoughts. How are you feeling today?</p>
            <div class="clinical-disclaimer" style="margin-top:20px; font-size: 0.85rem; color: #a0aec0; padding:12px; background: rgba(0,0,0,0.25); border-left: 4px solid #4fd1c5; border-radius:6px; text-align: left;">
                <i class="fa-solid fa-shield-heart" style="color:#4fd1c5; margin-right:5px;"></i> <strong>Clinical Safety Notice:</strong> I am an AI, not a medical professional. I cannot diagnose or prescribe medication. My support is not a substitute for clinical care. Please seek professional consultation for medical advice. If you are in high-risk crisis, I will escalate to emergency lines.
            </div>
        </div>
    `;
            currentSessionId = generateSessionId();
            fetchSessionMoodHistory(currentSessionId);
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }
            fetchChatHistory();
            messageInput.focus();
        };

        // Handle logout
        window.handleUserLogout = function () {
            USER_ID = null;
            chatWrapper.innerHTML = '';
            const chatHistoryList = document.getElementById('chatHistoryList');
            if (chatHistoryList) chatHistoryList.innerHTML = '';
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }
            if (window.globalChartInstance) {
                window.globalChartInstance.destroy();
                window.globalChartInstance = null;
            }
        };

        // --- UI Toggles ---
        openSidebarBtn.addEventListener('click', () => {
            moodSidebar.classList.remove('closed');
            openSidebarBtn.classList.add('hidden');
        });

        closeSidebarBtn.addEventListener('click', () => {
            moodSidebar.classList.add('closed');
            openSidebarBtn.classList.remove('hidden');
        });

        // --- Global Dashboard Toggle ---
        openGlobalDashboardBtn.addEventListener('click', () => {
            globalDashboardModal.classList.add('active');
            fetchGlobalMoodHistory();
        });

        closeGlobalDashboardBtn.addEventListener('click', () => {
            globalDashboardModal.classList.remove('active');
        });

        // --- Attachment Logic ---
        if (attachBtn) {
            attachBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                attachmentMenu.classList.toggle('show');
            });
        }

        if (attachImageBtn) {
            attachImageBtn.addEventListener('click', () => {
                fileInput.accept = "image/*";
                fileInput.click();
                attachmentMenu.classList.remove('show');
            });
        }

        if (attachFileBtn) {
            attachFileBtn.addEventListener('click', () => {
                fileInput.accept = ".pdf,.txt";
                fileInput.click();
                attachmentMenu.classList.remove('show');
            });
        }

        // Close menu when clicking outside
        document.addEventListener('click', (e) => {
            if (attachmentMenu && !attachmentMenu.contains(e.target) && !attachBtn.contains(e.target)) {
                attachmentMenu.classList.remove('show');
            }
        });

        if (fileInput) {
            fileInput.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (!file) return;

                // Set icon based on type
                if (file.type.startsWith('image/')) {
                    attachmentIcon.className = 'fa-solid fa-image';
                } else if (file.type === 'application/pdf') {
                    attachmentIcon.className = 'fa-solid fa-file-pdf';
                } else {
                    attachmentIcon.className = 'fa-solid fa-file-lines';
                }

                attachmentName.textContent = file.name;
                attachmentPreviewBox.style.display = 'flex';

                // Convert to Base64
                const reader = new FileReader();
                reader.onload = function (event) {
                    currentAttachment = {
                        type: file.type.startsWith('image/') ? 'image' : 'document',
                        data: event.target.result,
                        name: file.name
                    };
                };
                reader.readAsDataURL(file);
            });
        }

        if (removeAttachmentBtn) {
            removeAttachmentBtn.addEventListener('click', () => {
                clearAttachment();
            });
        }

        function clearAttachment() {
            currentAttachment = null;
            if (fileInput) fileInput.value = '';
            if (attachmentPreviewBox) attachmentPreviewBox.style.display = 'none';
        }

        // --- Chat Logic ---
        sendBtn.addEventListener('click', sendMessage);

        // Auto-resize textarea as user types
        messageInput.addEventListener('input', function () {
            this.style.height = 'auto'; // Reset height
            this.style.height = (this.scrollHeight) + 'px'; // Set to scroll height
            if (this.scrollHeight > 150) {
                this.style.overflowY = 'auto'; // Show scrollbar if it gets too tall
            } else {
                this.style.overflowY = 'hidden';
            }
        });

        // Handle Enter vs Shift+Enter
        messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault(); // Prevent default new line
                sendMessage();
            }
        });

        async function sendMessage() {
            const text = messageInput.value.trim();
            if (!text && !currentAttachment) return;

            // Clear welcome message if exists
            const welcome = document.querySelector('.welcome-message');
            if (welcome) welcome.style.display = 'none';

            // Render Attachment in User Bubble UI early
            let uiText = text;
            if (currentAttachment) {
                if (currentAttachment.type === 'image') {
                    uiText += `<br><img src="${currentAttachment.data}" style="max-width:200px; border-radius:10px; margin-top:10px; border:1px solid rgba(255,255,255,0.1);">`;
                } else {
                    uiText += `<br><div style="background:rgba(255,255,255,0.1); padding:8px 12px; border-radius:8px; display:inline-flex; align-items:center; gap:8px; margin-top:10px; border:1px solid rgba(255,255,255,0.05);"><i class="fa-solid fa-file-lines" style="color:#cbd5e1;"></i> <span style="font-size:0.9rem;">${currentAttachment.name}</span></div>`;
                }
            }
            if (!uiText) uiText = `<div style="color:rgba(255,255,255,0.7); font-style:italic;">[Attached ${currentAttachment.name}]</div>`;

            // Add user message
            appendMessage(uiText, 'user-msg');
            messageInput.value = '';
            messageInput.style.height = 'auto'; // Reset height after sending
            messageInput.disabled = true;

            // Prepare Payload
            const payload = {
                message: text || `[Attached file: ${currentAttachment?.name}]`,
                user_id: USER_ID,
                session_id: currentSessionId
            };

            if (currentAttachment) {
                payload.attachment_type = currentAttachment.type;
                payload.attachment_data = currentAttachment.data;
                payload.attachment_name = currentAttachment.name;
                clearAttachment();
            }

            // Show typing
            const typingId = appendTypingIndicator();

            try {
                const response = await fetch(`${BACKEND_URL}/ask`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await response.json();
                removeElement(typingId);

                let aiText = data.response || "Something went wrong.";
                let toolHtml = "";

                // Handle tool annotations from JSON payload
                if (data.tool_called && data.tool_called !== "None") {
                    toolHtml = `<span class="tool-badge"><i class="fa-solid fa-wrench"></i> Utilized: ${data.tool_called}</span>`;
                }

                // Strip out any accidental "WITH TOOL:" text if the LLM hallucinated it
                if (aiText.includes("WITH TOOL:")) {
                    aiText = aiText.split("WITH TOOL:")[0].trim();
                }

                appendMessage(aiText, 'ai-msg', toolHtml);

                // Refresh mood dashboard and history list
                setTimeout(() => fetchSessionMoodHistory(currentSessionId), 2000);
                fetchChatHistory();

            } catch (err) {
                removeElement(typingId);
                appendMessage("Error communicating with servers. Is the backend running?", 'ai-msg');
                console.error(err);
            } finally {
                messageInput.disabled = false;
                messageInput.focus();
            }
        }

        // --- DOM Helpers ---
        function appendMessage(text, className, extraHtml = "") {
            const div = document.createElement('div');
            div.className = `message ${className}`;

            // Convert markdown to true HTML using Marked.js
            let formattedText = "";
            try {
                // Use marked.parse with breaks enabled
                formattedText = marked.parse(text, { breaks: true });
            } catch {
                // Fallback to simple replace if marked fails to load
                formattedText = text.replace(/\n/g, '<br>');
            }

            div.innerHTML = `<div class="message-inner markdown-body">${formattedText}${extraHtml}</div>`;
            chatWrapper.appendChild(div);
            scrollToBottom();
        }

        function appendTypingIndicator() {
            const id = "typing-" + Date.now();
            const div = document.createElement('div');
            div.className = `message ai-msg`;
            div.id = id;
            div.innerHTML = `<div class="message-inner typing-indicator"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>`;
            chatWrapper.appendChild(div);
            scrollToBottom();
            return id;
        }

        function removeElement(id) {
            const el = document.getElementById(id);
            if (el) el.remove();
        }

        function scrollToBottom() {
            chatWrapper.scrollTop = chatWrapper.scrollHeight;
        }

        // --- Voice Recording Logic ---
        recordBtn.addEventListener('click', async () => {
            if (!isRecording) {
                startRecording();
            } else {
                stopRecording();
            }
        });

        async function startRecording() {
            if (!speechRecognition) {
                alert("Sorry, your browser doesn't support live speech recognition. Please use Google Chrome or Edge.");
                return;
            }

            try {
                messageInput.value = ""; // Clear for new dictation

                // Create a new empty message bubble for live transcription
                liveTranscriptionId = "live-transcript-" + Date.now();
                const div = document.createElement('div');
                div.className = `message user-msg`;
                div.id = liveTranscriptionId;
                div.innerHTML = `<div class="message-inner markdown-body">...listening...</div>`;
                chatWrapper.appendChild(div);
                scrollToBottom();

                speechRecognition.start();
                isRecording = true;
                recordBtn.classList.add('recording');
                recordingIndicator.classList.add('active');
                document.getElementById('recordingText').innerText = "Listening... Click to stop";
                messageInput.placeholder = "Listening...";
                // We do NOT disable the input so the user can see the text flowing in!

            } catch (err) {
                console.error("Failed to start speech recognition:", err);
            }
        }

        function stopRecording() {
            if (speechRecognition && isRecording) {
                speechRecognition.stop();
            }

            isRecording = false;

            // Remove the temporary live transcription bubble
            if (liveTranscriptionId) {
                removeElement(liveTranscriptionId);
                liveTranscriptionId = null;
            }

            // If there is text in the input box when we stop, 
            // we can either leave it there for the user to edit, or auto-send it.
            // We'll leave it in the input box so the user can review before pressing Send.

            recordBtn.classList.remove('recording');
            recordingIndicator.classList.remove('active');
            document.getElementById('recordingText').innerText = "Recording... Click to stop";
            messageInput.placeholder = "What's on your mind today?";
        }

        // --- Mood Dashboard Logic ---
        async function fetchGlobalMetrics() {
            try {
                const response = await fetch(`${BACKEND_URL}/global_metrics/${USER_ID}?t=${Date.now()}`);
                if (!response.ok) return;
                const metrics = await response.json();

                const snapshotContainer = document.getElementById('globalSnapshot');
                if (!snapshotContainer) return;

                let highText = "N/A";
                let lowText = "N/A";
                let highObj = { score: 0, title: '' };
                let lowObj = { score: 0, title: '' };

                if (metrics.highest_session) {
                    highObj = metrics.highest_session;
                    highText = highObj.title;
                }
                if (metrics.lowest_session) {
                    lowObj = metrics.lowest_session;
                    lowText = lowObj.title;
                }

                let lifePct = (metrics.lifetime_average / 10) * 100;
                let highPct = (highObj.score / 10) * 100;
                let lowPct = (lowObj.score / 10) * 100;

                let iconTrend = 'fa-arrow-right';
                let colorTrend = 'var(--text-muted)';
                if (metrics.trend.includes('Up')) { iconTrend = 'fa-arrow-trend-up'; colorTrend = '#4fd1c5'; }
                if (metrics.trend.includes('Down')) { iconTrend = 'fa-arrow-trend-down'; colorTrend = '#fc8181'; }

                snapshotContainer.innerHTML = `
            <div class="snapshot-card">
                <div class="snap-label">Lifetime Average</div>
                <div class="circular-progress" style="--val: ${lifePct};">
                    <span class="circular-value">${metrics.lifetime_average}</span>
                </div>
                <div class="snap-subtext">Across ${metrics.total_sessions} sessions</div>
            </div>
            <div class="snapshot-card">
                <div class="snap-label">Recent Trend</div>
                <div class="snap-value" style="color:${colorTrend}; font-size: 2.2rem; margin: 10px 0;"><i class="fa-solid ${iconTrend}"></i></div>
                <div class="snap-value" style="font-size: 1.1rem;">${metrics.trend.replace(/[↗↘→]/g, '').trim()}</div>
                <div class="snap-subtext">vs Lifetime Avg</div>
            </div>
            <div class="snapshot-card">
                <div class="snap-label" style="color: #4fd1c5;">Highest Point</div>
                <div class="circular-progress" style="--val: ${highPct}; --primary-color: #4fd1c5; width: 60px; height: 60px;">
                    <span class="circular-value" style="font-size: 1.1rem;">${highObj.score}</span>
                </div>
                <div class="snap-subtext" style="color: white; margin-top: 10px;">${highText}</div>
            </div>
            <div class="snapshot-card">
                <div class="snap-label" style="color: #fc8181;">Lowest Point</div>
                <div class="circular-progress" style="--val: ${lowPct}; --primary-color: #fc8181; width: 60px; height: 60px;">
                    <span class="circular-value" style="font-size: 1.1rem;">${lowObj.score}</span>
                </div>
                <div class="snap-subtext" style="color: white; margin-top: 10px;">${lowText}</div>
            </div>
        `;

                // Render Core Themes
                const themesContainer = document.getElementById('coreThemesContainer');
                const themesList = document.getElementById('coreThemesList');
                if (themesContainer && themesList && metrics.top_themes && metrics.top_themes.length > 0) {
                    themesContainer.style.display = 'block';
                    let html = '';
                    metrics.top_themes.forEach(themeObj => {
                        html += `
                <div style="background: rgba(40,40,55,0.7); border: 1px solid rgba(255, 255, 255, 0.08); padding: 10px 15px; border-radius: 12px; flex: 1; min-width: 150px; position: relative; overflow: hidden;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; position: relative; z-index: 2;">
                        <span style="color: #e2e8f0; font-size: 0.95rem; font-weight: 500; text-transform: capitalize;">${themeObj.theme}</span>
                        <span style="color: #4fd1c5; font-size: 0.95rem; font-weight: 600;">${themeObj.percentage}%</span>
                    </div>
                    <!-- Background Progress Bar -->
                    <div style="position: absolute; top: 0; left: 0; height: 100%; width: ${themeObj.percentage}%; background: linear-gradient(90deg, rgba(79, 209, 197, 0.15) 0%, rgba(79, 209, 197, 0.3) 100%); z-index: 1;"></div>
                </div>`;
                    });
                    themesList.innerHTML = html;
                } else if (themesContainer) {
                    themesContainer.style.display = 'none';
                }

            } catch (err) {
                console.error("Failed to fetch global metrics", err);
            }
        }

        async function fetchSessionMoodHistory(sessionId) {
            try {
                const response = await fetch(`${BACKEND_URL}/users/${USER_ID}/sessions/${sessionId}/mood?t=${Date.now()}`);
                if (!response.ok) return;
                const data = await response.json();

                if (data && data.length > 0) {
                    updateChart(data, 'moodChart', chartInstance, (instance) => { chartInstance = instance });
                    updateInsights(data);
                } else {
                    // Clear chart if no data
                    if (chartInstance) chartInstance.destroy();
                    recentInsights.innerHTML = '<p class="text-muted" style="color:var(--text-muted); font-size: 0.9rem;">No mood data for this session yet.</p>';
                }
            } catch (err) {
                console.error("Failed to fetch session mood history", err);
            }
        }

        let globalChartInstance = null;
        async function fetchGlobalMoodHistory() {
            try {
                await fetchGlobalMetrics(); // Populate the snapshot cards first

                // Fetch the aggregated sessions instead of granular mood history
                const response = await fetch(`${BACKEND_URL}/sessions/${USER_ID}?t=${Date.now()}`);
                if (!response.ok) return;
                const sessions = await response.json();

                // Extract and map sessions that have an aggregated score
                const data = sessions
                    .filter(s => s.aggregated_score !== null && s.aggregated_score !== undefined)
                    .map(s => ({
                        timestamp: s.timestamp,
                        score: s.aggregated_score,
                        summary: s.first_message
                    }));

                if (data && data.length > 0) {
                    updateChart(data, 'globalMoodChart', globalChartInstance, (instance) => { globalChartInstance = instance }, true);

                    // Create a container for the clicked insight if it doesn't exist
                    let detailsContainer = document.getElementById('globalInsightDetails');
                    if (!detailsContainer) {
                        detailsContainer = document.createElement('div');
                        detailsContainer.id = 'globalInsightDetails';
                        detailsContainer.className = 'global-metrics';
                        document.getElementById('globalMetrics').parentNode.insertBefore(detailsContainer, document.getElementById('globalMetrics'));
                    }
                    detailsContainer.innerHTML = '<p class="text-muted" style="text-align:center; margin-top: 20px;">Click on any point in the graph to view the detailed insight.</p>';
                }
            } catch (err) {
                console.error("Failed to fetch global mood history", err);
            }
        }

        // --- PDF Export Logic ---
        document.getElementById('exportPdfBtn').addEventListener('click', async () => {
            const btn = document.getElementById('exportPdfBtn');
            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzing Patient & Generating Report...';
            btn.disabled = true;

            try {
                // 1. Fetch AI Clinical Analysis from Backend
                const response = await fetch(`${BACKEND_URL}/generate_clinical_report/${USER_ID}`);
                if (!response.ok) throw new Error("Failed to fetch clinical report.");
                const data = await response.json();

                // 2. Parse Markdown and Inject into Hidden Print Template
                const printContentContainer = document.getElementById('printReportContent');
                printContentContainer.innerHTML = marked.parse(data.report || "No analysis generated.");

                // Ensure bold markdown renders correctly in the PDF
                const bolds = printContentContainer.querySelectorAll('strong');
                bolds.forEach(b => { b.style.color = '#1a202c'; b.style.fontWeight = 'bold'; });

                // Insert Date
                const dateStr = new Date().toLocaleDateString();
                document.getElementById('printReportDate').textContent = dateStr;

                // 3. Temporarily display the render template to capture it
                const printTemplate = document.getElementById('clinicalReportPrintTemplate');
                printTemplate.style.display = 'block';

                // 4. Capture high-res canvas (scale: 2 for print quality)
                const canvas = await html2canvas(printTemplate, { scale: 2, useCORS: true, backgroundColor: '#ffffff' });

                // Hide it again immediately
                printTemplate.style.display = 'none';

                // 5. Initialize jsPDF (portrait, mm, A4)
                const pdf = new jspdf.jsPDF('p', 'mm', 'a4');
                const pdfWidth = pdf.internal.pageSize.getWidth();
                const pageHeight = pdf.internal.pageSize.getHeight();
                const originalImageHeight = (canvas.height * pdfWidth) / canvas.width;

                let position = 0;
                let leftHeight = originalImageHeight;
                const imgData = canvas.toDataURL('image/png');

                // Add the first page
                pdf.addImage(imgData, 'PNG', 0, position, pdfWidth, originalImageHeight);
                leftHeight -= pageHeight;

                // Loop and add new pages if the content overflows
                while (leftHeight > 0) {
                    position = leftHeight - originalImageHeight;
                    pdf.addPage();
                    pdf.addImage(imgData, 'PNG', 0, position, pdfWidth, originalImageHeight);
                    leftHeight -= pageHeight;
                }

                // Download
                pdf.save(`Trisoul_Clinical_Analysis_${dateStr.replace(/\//g, '-')}.pdf`);

            } catch (err) {
                console.error("PDF Export Error:", err);
                alert("Failed to generate the Clinical Analysis PDF. Please try again.");
            } finally {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        });

        // --- AI Check-in Logic ---
        document.getElementById('generateCheckinBtn').addEventListener('click', async () => {
            const btn = document.getElementById('generateCheckinBtn');
            const container = document.getElementById('aiCheckinContainer');
            const textArea = document.getElementById('aiCheckinText');

            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating...';
            btn.disabled = true;

            try {
                const response = await fetch(`${BACKEND_URL}/generate_ai_checkin/${USER_ID}`);
                if (!response.ok) throw new Error("Network response was not ok");

                const data = await response.json();
                const reflection = data.reflection;

                // Display the container and render the markdown
                container.style.display = 'block';
                if (window.marked) {
                    textArea.innerHTML = marked.parse(reflection);
                } else {
                    // Fallback if marked.js fails to load
                    textArea.innerText = reflection;
                }

            } catch (err) {
                console.error("AI Check-in failed:", err);
                container.style.display = 'block';
                textArea.innerHTML = '<span style="color: #fc8181;">Sorry, I encountered an error while generating your reflection. Please try again later.</span>';
            } finally {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        });

        function updateChart(data, canvasId, currentInstance, setInstance, isGlobal = false) {
            const ctx = document.getElementById(canvasId).getContext('2d');

            // Sort data chronologically to prevent crazy overlapping lines
            const sortedData = [...data].sort((a, b) => getLocalDate(a.timestamp) - getLocalDate(b.timestamp));

            const chartData = sortedData.map(log => ({
                x: getLocalDate(log.timestamp),
                y: log.score,
                summary: log.summary, // Store summary for click events
                keywords: log.keywords || "" // Store keywords
            }));

            if (currentInstance) {
                currentInstance.destroy();
            }

            // Chart.js Configuration
            Chart.defaults.color = '#94a3b8';
            const newChart = new Chart(ctx, {
                type: 'line',
                data: {
                    datasets: [{
                        label: 'Mood Score (1-10)',
                        data: chartData,
                        borderColor: '#4fd1c5',
                        backgroundColor: 'rgba(79, 209, 197, 0.2)',
                        borderWidth: 2,
                        tension: 0.1, // Reduced tension for cleaner, less "loopy" lines
                        pointBackgroundColor: '#fff',
                        pointBorderColor: '#4fd1c5',
                        pointBorderWidth: 2,
                        pointRadius: 5,         // Slightly larger points for sessions
                        pointHoverRadius: 8,
                        hitRadius: 15,          // Larger hit radius to make clicking much easier!
                        fill: true,
                        spanGaps: true // Connects lines even if there are time gaps
                    }]
                },
                options: {
                    onClick: (e, activeElements, chart) => {
                        if (!isGlobal || activeElements.length === 0) return;

                        const dataIndex = activeElements[0].index;
                        const pointData = chartData[dataIndex];

                        const detailsContainer = document.getElementById('globalInsightDetails');
                        if (detailsContainer && pointData) {
                            const dateStr = pointData.x.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                            detailsContainer.innerHTML = `
                        <div class="insight-card" style="margin-top:20px; border-color: var(--primary-light);">
                            <div class="insight-header">
                                <span>${dateStr}</span>
                                <span class="insight-score" style="font-size:1.2rem;">${pointData.y}/10</span>
                            </div>
                            <div style="font-size: 0.85rem; color: var(--primary-color); margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;">Chat Topic Summarized</div>
                            <div class="insight-text" style="font-size:1.05rem; color: #fff;">${pointData.summary}</div>
                            ${pointData.keywords ? `<div style="font-size: 0.85rem; color: #94a3b8; margin-top: 15px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;">Trigger Keywords</div>
                            <div style="margin-top: 5px; display: flex; gap: 6px; flex-wrap: wrap;">
                                ${pointData.keywords.split(',').filter(kw => kw.trim() !== '').map(kw => `<span style="background: rgba(255,255,255,0.1); padding: 3px 8px; border-radius: 12px; font-size: 0.8rem; color: #fff;">${kw.trim()}</span>`).join('')}
                            </div>` : ''}
                        </div>
                    `;
                        }
                    },
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            type: 'time',
                            time: { tooltipFormat: 'MMM d, yyyy HH:mm' },
                            grid: { color: 'rgba(255,255,255,0.05)' }
                        },
                        y: {
                            min: 1, max: 10,
                            grid: { color: 'rgba(255,255,255,0.05)' }
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title: function (context) {
                                    if (isGlobal && context[0].raw.summary) {
                                        return context[0].raw.summary.length > 50 ? context[0].raw.summary.substring(0, 50) + '...' : context[0].raw.summary;
                                    }
                                    return context[0].label;
                                },
                                label: function (context) {
                                    return `Score: ${context.raw.y}/10`;
                                }
                            }
                        },
                        zoom: { // Added Zoom & Pan Plugin Configuration
                            pan: {
                                enabled: isGlobal,
                                mode: 'x', // Only pan horizontally across time
                            },
                            zoom: {
                                wheel: { enabled: isGlobal },
                                pinch: { enabled: isGlobal },
                                mode: 'x', // Only zoom horizontally across time
                            }
                        }
                    }
                }
            });

            setInstance(newChart);
        }

        function updateInsights(data) {
            recentInsights.innerHTML = '';
            // Show all insights, reversed (newest first)
            const recent = data.slice().reverse();

            recent.forEach(log => {
                const dateStr = getLocalDate(log.timestamp).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

                const card = document.createElement('div');
                card.className = 'insight-card';
                card.innerHTML = `
            <div class="insight-header">
                <span>${dateStr}</span>
                <span class="insight-score">${log.score}/10</span>
            </div>
            <div class="insight-text">${log.summary}</div>
        `;
                recentInsights.appendChild(card);
            });
        }

        // --- Chat History Logic ---
        async function fetchChatHistory() {
            try {
                const response = await fetch(`${BACKEND_URL}/sessions/${USER_ID}?t=${Date.now()}`);
                if (!response.ok) return;
                const sessions = await response.json();

                chatHistoryList.innerHTML = '';

                if (sessions.length === 0) {
                    chatHistoryList.innerHTML = '<div class="history-item">No past chats yet.</div>';
                    return;
                }

                sessions.forEach(session => {
                    const dateStr = getLocalDate(session.timestamp).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                    let firstMsg = session.first_message;

                    const item = document.createElement('div');
                    item.className = 'history-item';
                    if (session.session_id === currentSessionId) item.classList.add('active');

                    let scoreBadge = '';
                    if (session.aggregated_score !== null && session.aggregated_score !== undefined) {
                        // simple numeric mapping for colors
                        let color = "var(--text-muted)";
                        if (session.aggregated_score >= 7) color = "#4fd1c5"; // green
                        else if (session.aggregated_score <= 3) color = "#fc8181"; // red
                        else color = "#f6e05e"; // yellow

                        scoreBadge = `<span style="color: ${color}; font-weight: bold; margin-left: 5px;">[Score: ${session.aggregated_score}]</span>`;
                    }

                    item.innerHTML = `
                <span class="history-time">${dateStr} ${scoreBadge}</span>
                <span class="history-text">${firstMsg}</span>
            `;
                    item.onclick = () => loadSessionMessages(session.session_id);
                    chatHistoryList.appendChild(item);
                });
            } catch (err) {
                chatHistoryList.innerHTML = '<div class="history-item">Failed to load history.</div>';
                console.error("Fetch chat history failed", err);
            }
        }

        async function loadSessionMessages(sessionId) {
            try {
                currentSessionId = sessionId;
                const response = await fetch(`${BACKEND_URL}/users/${USER_ID}/sessions/${sessionId}/messages?t=${Date.now()}`);
                if (!response.ok) return;
                const messages = await response.json();

                chatWrapper.innerHTML = ''; // Clear chat

                if (messages.length === 0) return;

                messages.forEach(msg => {
                    // Reconstruct tool badges if it's an AI message (for simplicity, we skip tool UI reconstruction from history unless saved, but text is guaranteed)
                    const className = msg.sender === 'user' ? 'user-msg' : 'ai-msg';
                    appendMessage(msg.text, className, "");
                });

                fetchChatHistory(); // Reset active visual styling
                fetchSessionMoodHistory(currentSessionId); // Load the specific mood for this chat
            } catch (err) {
                console.error("Load session failed", err);
            }
        }

        newChatBtnPrimary.addEventListener('click', () => {
            currentSessionId = generateSessionId();
            chatWrapper.innerHTML = `
        <div class="welcome-message">
            <div class="welcome-icon"><i class="fa-solid fa-leaf"></i></div>
            <h2>Welcome to Trisoul</h2>
            <p>I'm here to listen, support, and help you navigate your thoughts. How are you feeling today?</p>
            <div class="clinical-disclaimer" style="margin-top:20px; font-size: 0.85rem; color: #a0aec0; padding:12px; background: rgba(0,0,0,0.25); border-left: 4px solid #4fd1c5; border-radius:6px; text-align: left;">
                <i class="fa-solid fa-shield-heart" style="color:#4fd1c5; margin-right:5px;"></i> <strong>Clinical Safety Notice:</strong> I am an AI, not a medical professional. I cannot diagnose or prescribe medication. My support is not a substitute for clinical care. Please seek professional consultation for medical advice. If you are in high-risk crisis, I will escalate to emergency lines.
            </div>
        </div>
    `;
            fetchChatHistory(); // Clear active styling
            fetchSessionMoodHistory(currentSessionId); // Clear mood history since it's a new session
        });
    }
});
