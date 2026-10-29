(function(){
  const form=document.getElementById('student-feedback-form');
  if(!form)return;
  const mealRadios=Array.from(form.querySelectorAll('input[name="meal_type"]'));
  const localDate=document.getElementById('meal_date');
  const dishName=document.getElementById('dish_name');
  const dishRating=Array.from(form.querySelectorAll('input[name="dish_rating"]'));
  const submit=document.getElementById('submit-feedback');
  function selectMeal(){
    const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Jerusalem',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date());
    const hour=Number(parts.find(p=>p.type==='hour').value);
    const chosen=hour>=5&&hour<10?'breakfast':hour>=10&&hour<16?'lunch':'dinner';
    const selected=mealRadios.some(r=>r.checked);
    if(!selected||!form.dataset.mealTouched){const radio=mealRadios.find(r=>r.value===chosen);if(radio)radio.checked=true;}
    mealRadios.forEach(r=>r.addEventListener('change',()=>form.dataset.mealTouched='1'));
    const dateParts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Jerusalem',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const datePart=type=>dateParts.find(p=>p.type===type).value;
    localDate.value=datePart('year')+'-'+datePart('month')+'-'+datePart('day');
  }
  selectMeal();
  const dishSection=document.querySelector('.dish-panel');
  form.addEventListener('submit',function(event){
    const name=dishName.value.trim();
    const rating=dishRating.find(r=>r.checked);
    if((name&&!rating)||(!name&&rating)){
      event.preventDefault();
      dishSection.classList.add('dish-needs-attention');
      dishName.setCustomValidity(name&&!rating?'Please select a rating for this dish.':'Please enter the dish name to go with the rating.');
      if(!name)dishName.reportValidity();else {dishName.setCustomValidity('');dishRating[0].focus();}
      return;
    }
    dishName.setCustomValidity('');
    // The server validates and persists optional ratings in the existing comments field.
    submit.disabled=true;
    submit.querySelector('span').textContent=document.documentElement.lang==='he'?'שולח…':'Sending…';
    submit.setAttribute('aria-busy','true');
  });
  dishName.addEventListener('input',()=>dishName.setCustomValidity(''));
  dishRating.forEach(r=>r.addEventListener('change',()=>dishName.setCustomValidity('')));
})();
