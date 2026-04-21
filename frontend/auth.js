import { initializeApp } from "https://www.gstatic.com/firebasejs/10.9.0/firebase-app.js";
import { getAuth, createUserWithEmailAndPassword, signInWithEmailAndPassword, onAuthStateChanged, signOut, updateProfile } from "https://www.gstatic.com/firebasejs/10.9.0/firebase-auth.js";

const BACKEND_URL = "http://localhost:8000";
const BENCH_SESSION_KEY = "trisoul_bench_user_id";

const firebaseConfig = window.TRISOUL_FIREBASE_CONFIG;

if (!firebaseConfig) {
    throw new Error("Missing Firebase config. Create frontend/firebase-config.js from frontend/firebase-config.example.js.");
}

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

// DOM Elements
const authModal = document.getElementById('authModal');
const authForm = document.getElementById('authForm');
const authEmail = document.getElementById('authEmail');
const authPassword = document.getElementById('authPassword');
const authToggleText = document.getElementById('authToggleText');
const authSubmitBtn = document.getElementById('authSubmitBtn');
const authError = document.getElementById('authError');
const logoutBtn = document.getElementById('logoutBtn');
const benchUserId = document.getElementById('benchUserId');
const benchPassword = document.getElementById('benchPassword');
const benchLoginBtn = document.getElementById('benchLoginBtn');

// New Auth DOM Elements
const authHeaderTitle = document.querySelector('.auth-header h2');
const authHeaderDesc = document.querySelector('.auth-header p');
const signupFields = document.getElementById('signupFields');
const signupConfirmPasswordField = document.getElementById('signupConfirmPasswordField');
const authFirstName = document.getElementById('authFirstName');
const authLastName = document.getElementById('authLastName');
const authDob = document.getElementById('authDob');
const authConfirmPassword = document.getElementById('authConfirmPassword');

let isSignup = false;

function showAppForUser(userId) {
    authModal.classList.remove('active');
    const landingPage = document.getElementById('landingPage');
    const mainAppContainer = document.getElementById('mainAppContainer');

    if (landingPage && mainAppContainer) {
        landingPage.classList.remove('active');
        landingPage.style.display = 'none';
        mainAppContainer.style.display = 'flex';
    }

    if (window.initializeAppWithUser) {
        window.initializeAppWithUser(userId);
    }
}

function clearBenchSession() {
    localStorage.removeItem(BENCH_SESSION_KEY);
}

// Handle Auth Toggle (Login vs Signup)
authToggleText.addEventListener('click', () => {
    isSignup = !isSignup;
    authError.style.display = 'none';
    authForm.reset();

    if (isSignup) {
        authHeaderTitle.innerText = "Create an Account";
        authHeaderDesc.innerText = "Join us to start your personal journey.";
        authSubmitBtn.textContent = 'Sign Up';
        authToggleText.innerHTML = 'Already have an account? <span>Log In</span>';
        authPassword.placeholder = "Create Password";

        // Show signup fields
        if (signupFields) signupFields.style.display = 'block';
        if (signupConfirmPasswordField) signupConfirmPasswordField.style.display = 'block';

        // Make signup fields required
        if (authFirstName) authFirstName.setAttribute('required', 'true');
        if (authLastName) authLastName.setAttribute('required', 'true');
        if (authDob) authDob.setAttribute('required', 'true');
        if (authConfirmPassword) authConfirmPassword.setAttribute('required', 'true');

    } else {
        authHeaderTitle.innerText = "Welcome to Trisoul";
        authHeaderDesc.innerText = "Please log in to continue your journey.";
        authSubmitBtn.textContent = 'Log In';
        authToggleText.innerHTML = 'Need an account? <span>Sign Up</span>';
        authPassword.placeholder = "Password";

        // Hide signup fields
        if (signupFields) signupFields.style.display = 'none';
        if (signupConfirmPasswordField) signupConfirmPasswordField.style.display = 'none';

        // Remove required attributes from signup fields
        if (authFirstName) authFirstName.removeAttribute('required');
        if (authLastName) authLastName.removeAttribute('required');
        if (authDob) authDob.removeAttribute('required');
        if (authConfirmPassword) authConfirmPassword.removeAttribute('required');
    }
});

// Handle Submit
authForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = authEmail.value;
    const password = authPassword.value;

    try {
        authSubmitBtn.disabled = true;
        authSubmitBtn.textContent = 'Processing...';
        authError.style.display = 'none';

        if (isSignup) {
            // Validate Password match
            if (password !== authConfirmPassword.value) {
                throw new Error("Passwords do not match. Please try again.");
            }

            const userCredential = await createUserWithEmailAndPassword(auth, email, password);

            // Optionally, update user's profile with their First and Last Name
            if (authFirstName && authLastName) {
                const displayName = `${authFirstName.value} ${authLastName.value}`.trim();
                await updateProfile(userCredential.user, {
                    displayName: displayName
                });
            }

            // Note: DOB would typically be stored in a separate Firestore/database document
            // linked to userCredential.user.uid. We are verifying it locally here.

        } else {
            await signInWithEmailAndPassword(auth, email, password);
        }
    } catch (error) {
        authError.textContent = error.message;
        authError.style.display = 'block';
    } finally {
        authSubmitBtn.disabled = false;
        authSubmitBtn.textContent = isSignup ? 'Sign Up' : 'Log In';
    }
});

// Handle Logout
if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
        clearBenchSession();
        signOut(auth).finally(() => {
            if (window.handleUserLogout) {
                window.handleUserLogout();
            }
        });
    });
}

if (benchLoginBtn) {
    benchLoginBtn.addEventListener('click', async () => {
        const userId = benchUserId.value.trim();
        const password = benchPassword.value;

        try {
            benchLoginBtn.disabled = true;
            benchLoginBtn.textContent = 'Opening...';
            authError.style.display = 'none';

            const response = await fetch(`${BACKEND_URL}/testbench/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId, password })
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || "Benchmark login failed.");
            }

            await signOut(auth).catch(() => {});
            localStorage.setItem(BENCH_SESSION_KEY, data.user_id);
            showAppForUser(data.user_id);
        } catch (error) {
            authError.textContent = error.message;
            authError.style.display = 'block';
        } finally {
            benchLoginBtn.disabled = false;
            benchLoginBtn.textContent = 'Open Bench User';
        }
    });
}

// Track Auth State and communicate with main script.js
onAuthStateChanged(auth, (user) => {
    if (user) {
        clearBenchSession();
        // User is signed in.
        showAppForUser(user.uid);
    } else {
        const benchUser = localStorage.getItem(BENCH_SESSION_KEY);
        if (benchUser) {
            showAppForUser(benchUser);
            return;
        }

        // User is signed out.
        // Don't show login modal immediately if landing page is visible
        const landingPage = document.getElementById('landingPage');
        if (!landingPage || !landingPage.classList.contains('active')) {
            authModal.classList.add('active');
        }

        if (window.handleUserLogout) {
            window.handleUserLogout();

            // Re-show landing page on logout
            if (landingPage && mainAppContainer) {
                mainAppContainer.style.display = 'none';
                landingPage.style.display = 'flex';
                landingPage.style.opacity = '1';
                setTimeout(() => landingPage.classList.add('active'), 10);
            }
        }
    }
});
