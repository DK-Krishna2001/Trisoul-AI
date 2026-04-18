import { initializeApp } from "https://www.gstatic.com/firebasejs/10.9.0/firebase-app.js";
import { getAuth, createUserWithEmailAndPassword, signInWithEmailAndPassword, onAuthStateChanged, signOut, updateProfile } from "https://www.gstatic.com/firebasejs/10.9.0/firebase-auth.js";

// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
    apiKey: "your_firebase_web_api_key",
    authDomain: "your_project.firebaseapp.com",
    projectId: "your_project_id",
    storageBucket: "your_project.firebasestorage.app",
    messagingSenderId: "your_sender_id",
    appId: "your_firebase_app_id",
    measurementId: "your_measurement_id"
};

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
        signOut(auth);
    });
}

// Track Auth State and communicate with main script.js
onAuthStateChanged(auth, (user) => {
    if (user) {
        // User is signed in.
        authModal.classList.remove('active');
        const landingPage = document.getElementById('landingPage');
        const mainAppContainer = document.getElementById('mainAppContainer');

        // If user is logged in natively, immediately skip the landing page
        if (landingPage) {
            landingPage.classList.remove('active');
            landingPage.style.display = 'none';
            mainAppContainer.style.display = 'flex';
        }

        // Tell main script to initialize with user.uid
        if (window.initializeAppWithUser) {
            window.initializeAppWithUser(user.uid);
        }
    } else {
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
