document.addEventListener('DOMContentLoaded', () => {
    document.addEventListener('mousemove', (e) => {
        const phone = document.querySelector('.phone');
        const xAxis = (window.innerWidth / 2 - e.pageX) / 50;
        const yAxis = (window.innerHeight / 2 - e.pageY) / 50;
        phone.style.transform = `rotateY(${xAxis}deg) rotateX(${yAxis}deg)`;
    });

    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            document.querySelector(this.getAttribute('href')).scrollIntoView({
                behavior: 'smooth'
            });
        });
    });

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, {
        threshold: 0.1
    });

    document.querySelectorAll('.feature').forEach(feature => {
        observer.observe(feature);
    });

    const logos = document.querySelectorAll('.logo');
    logos.forEach(logo => {
        logo.addEventListener('mouseover', () => {
            logo.style.transform = 'scale(1.1) rotate(10deg)';
        });
        logo.addEventListener('mouseout', () => {
            logo.style.transform = 'scale(1) rotate(0deg)';
        });
    });
});
